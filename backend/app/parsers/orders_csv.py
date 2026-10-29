"""Canonical Orders CSV parser and ingest validation for TradeMirror.

Responsibility:
Ingests and validates CSV order books matching the canonical schema:
order_id, timestamp, symbol, instrument_type, strike, expiry, side, quantity,
lot_size, price, status.
Validates headers, normalizes fields to domain types, classifies invalid/rejected/duplicate rows,
and returns clean Order objects sorted by timestamp ascending with ties broken by order_id.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import IO, Any

from app.models import Order

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

CANONICAL_COLUMNS = [
    "order_id",
    "timestamp",
    "symbol",
    "instrument_type",
    "strike",
    "expiry",
    "side",
    "quantity",
    "lot_size",
    "price",
    "status",
]


class IngestError(Exception):
    """Raised when the CSV schema, file structure, or encoding is fatally invalid."""


@dataclass(frozen=True)
class IngestWarning:
    """Non-fatal warning recorded during row parsing."""

    code: str
    row_number: int  # 1-based, excluding header
    order_id: str | None
    message: str


@dataclass
class IngestResult:
    """Result of order book ingestion containing cleaned orders and audit metrics."""

    orders: list[Order]
    warnings: list[IngestWarning]
    counts: dict[str, int]


def _read_source_to_text(source: str | Path | bytes | IO[Any]) -> str:
    """Read source content into a decoded text string."""
    if isinstance(source, Path):
        if not source.exists():
            raise IngestError(f"File not found: {source}")
        try:
            return source.read_text(encoding="utf-8")
        except UnicodeDecodeError as err:
            raise IngestError(f"Failed to decode file as UTF-8: {err}") from err

    if isinstance(source, bytes):
        try:
            return source.decode("utf-8")
        except UnicodeDecodeError as err:
            raise IngestError(f"Failed to decode bytes as UTF-8: {err}") from err

    if isinstance(source, (StringIO, BytesIO)) or hasattr(source, "read"):
        content = source.read()
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError as err:
                raise IngestError(f"Failed to decode stream as UTF-8: {err}") from err
        return str(content)

    if isinstance(source, str):
        # Check if source string is an existing file path
        try:
            p = Path(source)
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except (OSError, ValueError):
            pass
        return source

    raise IngestError(f"Unsupported source type: {type(source).__name__}")


def _parse_timestamp(ts_str: str) -> tuple[datetime, bool]:
    """Parse timestamp string into timezone-aware datetime and is_naive flag."""
    ts_clean = ts_str.strip()

    # Try common formats
    formats = [
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(ts_clean, fmt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=IST), True
            return dt, False
        except ValueError:
            continue

    # Try fromisoformat as fallback
    try:
        dt = datetime.fromisoformat(ts_clean)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=IST), True
        return dt, False
    except ValueError as err:
        raise ValueError(f"Cannot parse timestamp: '{ts_clean}'") from err


def _parse_date(date_str: str) -> date:
    """Parse expiry date string into a date object."""
    d_clean = date_str.strip()
    for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"]:
        try:
            return datetime.strptime(d_clean, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(d_clean)
    except ValueError as err:
        raise ValueError(f"Cannot parse expiry date: '{d_clean}'") from err


def parse_orders(source: str | Path | bytes | IO[Any]) -> IngestResult:
    """Parse canonical orders CSV into an IngestResult with cleaned, sorted orders."""
    text_content = _read_source_to_text(source)
    if not text_content or not text_content.strip():
        raise IngestError("no orders found")

    reader = csv.reader(StringIO(text_content))
    try:
        raw_header = next(reader)
    except StopIteration:
        raise IngestError("no orders found") from None

    if not raw_header:
        raise IngestError("no orders found")

    # Validate header
    header_norm = [c.strip().lower() for c in raw_header]
    canonical_set = {c.lower() for c in CANONICAL_COLUMNS}
    present_set = set(header_norm)

    missing = canonical_set - present_set
    unexpected = present_set - canonical_set

    if missing or unexpected:
        error_parts = []
        if missing:
            error_parts.append(f"missing required columns: {sorted(missing)}")
        if unexpected:
            error_parts.append(f"unexpected columns: {sorted(unexpected)}")
        raise IngestError(f"Schema mismatch: {', '.join(error_parts)}")

    # Map column index
    col_idx = {name: header_norm.index(name.lower()) for name in CANONICAL_COLUMNS}

    warnings: list[IngestWarning] = []
    counts: dict[str, int] = {
        "raw_rows": 0,
        "kept": 0,
        "duplicates": 0,
        "rejected": 0,
        "missing_price": 0,
        "invalid": 0,
    }

    seen_raw_rows: set[tuple[str, ...]] = set()
    cleaned_orders: list[Order] = []
    assumed_ist_warned = False

    row_number = 0
    for row in reader:
        if not row or all(not cell.strip() for cell in row):
            continue

        row_number += 1
        counts["raw_rows"] += 1

        # Check exact row column length
        if len(row) < len(raw_header):
            counts["invalid"] += 1
            warnings.append(
                IngestWarning(
                    code="invalid",
                    row_number=row_number,
                    order_id=None,
                    message=f"Row has {len(row)} columns, expected {len(raw_header)}",
                )
            )
            continue

        # Extract fields
        order_id = row[col_idx["order_id"]].strip()
        timestamp_raw = row[col_idx["timestamp"]].strip()
        symbol_raw = row[col_idx["symbol"]].strip()
        inst_type_raw = row[col_idx["instrument_type"]].strip()
        strike_raw = row[col_idx["strike"]].strip()
        expiry_raw = row[col_idx["expiry"]].strip()
        side_raw = row[col_idx["side"]].strip()
        quantity_raw = row[col_idx["quantity"]].strip()
        lot_size_raw = row[col_idx["lot_size"]].strip()
        price_raw = row[col_idx["price"]].strip()
        status_raw = row[col_idx["status"]].strip()

        # Build canonical tuple for duplicate detection
        canonical_row_tuple = (
            order_id,
            timestamp_raw,
            symbol_raw,
            inst_type_raw,
            strike_raw,
            expiry_raw,
            side_raw,
            quantity_raw,
            lot_size_raw,
            price_raw,
            status_raw,
        )

        # Rule 1: Duplicate check (precedence 1)
        if canonical_row_tuple in seen_raw_rows:
            counts["duplicates"] += 1
            warnings.append(
                IngestWarning(
                    code="duplicate",
                    row_number=row_number,
                    order_id=order_id if order_id else None,
                    message="Exact duplicate row dropped",
                )
            )
            continue
        seen_raw_rows.add(canonical_row_tuple)

        # Rule 2: Rejected check (precedence 2)
        if status_raw.upper() != "COMPLETE":
            counts["rejected"] += 1
            warnings.append(
                IngestWarning(
                    code="rejected",
                    row_number=row_number,
                    order_id=order_id if order_id else None,
                    message=f"Order status '{status_raw}' is not COMPLETE",
                )
            )
            continue

        # Rule 3: Missing price or quantity (precedence 3)
        price_val: float | None = None
        qty_val: int | None = None
        has_missing_price = False

        if not price_raw:
            has_missing_price = True
        else:
            try:
                price_val = float(price_raw)
                if price_val <= 0:
                    has_missing_price = True
            except ValueError:
                has_missing_price = True

        if not quantity_raw:
            has_missing_price = True
        else:
            try:
                qty_val = int(quantity_raw)
                if qty_val <= 0:
                    has_missing_price = True
            except ValueError:
                has_missing_price = True

        if has_missing_price:
            counts["missing_price"] += 1
            warnings.append(
                IngestWarning(
                    code="missing_price",
                    row_number=row_number,
                    order_id=order_id if order_id else None,
                    message="Price or quantity missing, non-numeric, or <= 0",
                )
            )
            continue

        # Rule 4: Invalid fields (precedence 4)
        invalid_field: str | None = None
        parsed_ts: datetime | None = None
        is_naive = False

        try:
            parsed_ts, is_naive = _parse_timestamp(timestamp_raw)
        except ValueError:
            invalid_field = "timestamp"

        side_upper = side_raw.upper()
        if invalid_field is None and side_upper not in ("BUY", "SELL"):
            invalid_field = "side"

        inst_type_upper = inst_type_raw.upper()
        if invalid_field is None and inst_type_upper not in ("CE", "PE"):
            invalid_field = "instrument_type"

        strike_val: float | None = None
        if invalid_field is None:
            try:
                strike_val = float(strike_raw)
                if strike_val <= 0:
                    invalid_field = "strike"
            except ValueError:
                invalid_field = "strike"

        lot_size_val: int | None = None
        if invalid_field is None:
            try:
                lot_size_val = int(lot_size_raw)
                if lot_size_val <= 0:
                    invalid_field = "lot_size"
            except ValueError:
                invalid_field = "lot_size"

        expiry_val: date | None = None
        if invalid_field is None:
            try:
                expiry_val = _parse_date(expiry_raw)
            except ValueError:
                invalid_field = "expiry"

        if invalid_field is not None:
            counts["invalid"] += 1
            warnings.append(
                IngestWarning(
                    code="invalid",
                    row_number=row_number,
                    order_id=order_id if order_id else None,
                    message=f"Invalid unparseable field: {invalid_field}",
                )
            )
            continue

        # Valid row: record assumed_ist once per file if naive timestamp encountered
        if is_naive and not assumed_ist_warned:
            warnings.append(
                IngestWarning(
                    code="assumed_ist",
                    row_number=row_number,
                    order_id=order_id if order_id else None,
                    message="Naive timestamps encountered; assumed IST (+05:30)",
                )
            )
            assumed_ist_warned = True

        assert parsed_ts is not None
        assert strike_val is not None
        assert lot_size_val is not None
        assert expiry_val is not None
        assert price_val is not None
        assert qty_val is not None

        order = Order(
            order_id=order_id,
            timestamp=parsed_ts,
            symbol=symbol_raw.upper(),
            instrument_type=inst_type_upper,
            strike=strike_val,
            expiry=expiry_val,
            side=side_upper,
            quantity=qty_val,
            lot_size=lot_size_val,
            price=price_val,
            status=status_raw.upper(),
        )
        cleaned_orders.append(order)
        counts["kept"] += 1

    if counts["raw_rows"] == 0:
        raise IngestError("no orders found")

    # Sort ascending by timestamp, ties broken by order_id
    cleaned_orders.sort(key=lambda o: (o.timestamp, o.order_id))

    return IngestResult(
        orders=cleaned_orders,
        warnings=warnings,
        counts=counts,
    )
