"""Tests for canonical CSV orders parser and ingest validation."""

import json
from datetime import date, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path

import pytest
from app.parsers.orders_csv import IngestError, parse_orders

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

SAMPLE_HEADER = (
    "order_id,timestamp,symbol,instrument_type,strike,expiry,side,quantity,lot_size,price,status\n"
)


def _row(
    oid: str = "O1",
    ts: str = "2024-10-01 09:20:00+0530",
    sym: str = "NIFTY24OCT25000CE",
    inst: str = "CE",
    strike: str = "25000",
    expiry: str = "2024-10-31",
    side: str = "BUY",
    qty: str = "75",
    lot: str = "75",
    price: str = "100.5",
    status: str = "COMPLETE",
) -> str:
    """Format a CSV row under test."""
    return f"{oid},{ts},{sym},{inst},{strike},{expiry},{side},{qty},{lot},{price},{status}\n"


def test_all_generated_datasets_parse_without_error() -> None:
    """Verify each dataset in data/datasets/ parses without error."""
    datasets_dir = Path("data/datasets")
    assert datasets_dir.exists()

    csv_files = list(datasets_dir.glob("*.csv"))
    assert len(csv_files) >= 8

    for csv_file in csv_files:
        result = parse_orders(csv_file)
        assert len(result.orders) > 0
        assert result.counts["raw_rows"] > 0
        assert result.counts["kept"] > 0


def test_messy_dataset_counts_match_ground_truth() -> None:
    """Verify messy.csv counts for duplicates, rejected, missing_price match ground truth."""
    csv_path = Path("data/datasets/messy.csv")
    gt_path = Path("data/ground_truth/messy.json")

    assert csv_path.exists()
    assert gt_path.exists()

    result = parse_orders(csv_path)
    with open(gt_path, encoding="utf-8") as f:
        gt = json.load(f)

    expected = gt["expected_ingest_warnings"]
    assert (
        result.counts["duplicates"] == expected["duplicates"]
    ), f"Parser duplicates {result.counts['duplicates']} != expected {expected['duplicates']}"
    assert (
        result.counts["rejected"] == expected["rejected"]
    ), f"Parser rejected {result.counts['rejected']} != expected {expected['rejected']}"
    assert result.counts["missing_price"] == expected["missing_price"], (
        f"Parser missing_price {result.counts['missing_price']} != "
        f"expected {expected['missing_price']}"
    )


def test_clean_dataset_zero_warnings() -> None:
    """Verify clean.csv produces zero warnings and kept == raw_rows."""
    csv_path = Path("data/datasets/clean.csv")
    result = parse_orders(csv_path)

    assert len(result.warnings) == 0
    assert result.counts["kept"] == result.counts["raw_rows"]
    assert result.counts["duplicates"] == 0
    assert result.counts["rejected"] == 0
    assert result.counts["missing_price"] == 0
    assert result.counts["invalid"] == 0


def test_sorting_order_ascending() -> None:
    """Verify output orders are strictly sorted ascending by timestamp and order_id."""
    csv_path = Path("data/datasets/messy.csv")
    result = parse_orders(csv_path)

    for i in range(len(result.orders) - 1):
        curr = result.orders[i]
        nxt = result.orders[i + 1]
        assert (curr.timestamp, curr.order_id) <= (nxt.timestamp, nxt.order_id)


def test_schema_missing_column_raises() -> None:
    """Verify missing required column raises IngestError naming missing column."""
    bad_header = (
        "order_id,timestamp,symbol,instrument_type,expiry,side,quantity,lot_size,price,status\n"
    )
    row = "ORD1,2024-10-01 09:20:00+0530,NIFTY,CE,2024-10-31,BUY,75,75,100,COMPLETE\n"
    csv_data = bad_header + row

    with pytest.raises(IngestError) as exc_info:
        parse_orders(csv_data)

    assert "missing required columns" in str(exc_info.value)
    assert "strike" in str(exc_info.value)


def test_schema_extra_column_raises() -> None:
    """Verify unexpected column raises IngestError naming unexpected column."""
    bad_header = (
        "order_id,timestamp,symbol,instrument_type,strike,expiry,"
        "side,quantity,lot_size,price,status,broker\n"
    )
    csv_data = (
        bad_header
        + "ORD1,2024-10-01 09:20:00+0530,NIFTY,CE,25000,2024-10-31,BUY,75,75,100,COMPLETE,ZERODHA\n"
    )

    with pytest.raises(IngestError) as exc_info:
        parse_orders(csv_data)

    assert "unexpected columns" in str(exc_info.value)
    assert "broker" in str(exc_info.value)


def test_schema_empty_and_header_only_raises() -> None:
    """Verify empty file or header-only file raises IngestError('no orders found')."""
    with pytest.raises(IngestError, match="no orders found"):
        parse_orders("")

    with pytest.raises(IngestError, match="no orders found"):
        parse_orders("   \n\n  ")

    with pytest.raises(IngestError, match="no orders found"):
        parse_orders(SAMPLE_HEADER)


def test_schema_case_insensitive_and_whitespace_headers() -> None:
    """Verify case-insensitive and whitespace-padded headers succeed."""
    header = (
        " ORDER_ID , TimeStamp , SYMBOL , instrument_type , Strike , Expiry , "
        "Side , Quantity , Lot_Size , Price , STATUS \n"
    )
    row = _row(oid="ORD01", price="100.5")
    result = parse_orders(header + row)

    assert len(result.orders) == 1
    order = result.orders[0]
    assert order.order_id == "ORD01"
    assert order.symbol == "NIFTY24OCT25000CE"
    assert order.side == "BUY"
    assert order.status == "COMPLETE"
    assert order.price == 100.5
    assert order.quantity == 75
    assert order.expiry == date(2024, 10, 31)


def test_row_rule_duplicate() -> None:
    """Verify duplicate row is dropped, first kept, and counted as duplicate."""
    row = _row(oid="ORD01")
    content = SAMPLE_HEADER + row + row

    result = parse_orders(content)
    assert result.counts["raw_rows"] == 2
    assert result.counts["kept"] == 1
    assert result.counts["duplicates"] == 1
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "duplicate"
    assert result.warnings[0].row_number == 2


def test_row_rule_rejected() -> None:
    """Verify non-COMPLETE row is dropped and counted as rejected."""
    row = _row(oid="ORD01", status="REJECTED")
    valid_row = _row(oid="ORD02", status="COMPLETE")
    result = parse_orders(SAMPLE_HEADER + row + valid_row)

    assert result.counts["raw_rows"] == 2
    assert result.counts["kept"] == 1
    assert result.counts["rejected"] == 1
    assert result.warnings[0].code == "rejected"
    assert result.warnings[0].row_number == 1


def test_row_rule_missing_price_or_quantity() -> None:
    """Verify missing/empty/non-numeric/negative price or quantity is dropped."""
    r1 = _row(oid="ORD01", price="")
    r2 = _row(oid="ORD02", price="-10")
    r3 = _row(oid="ORD03", qty="0")
    r4 = _row(oid="ORD04", qty="NaN")
    v1 = _row(oid="ORD05", price="50")

    result = parse_orders(SAMPLE_HEADER + r1 + r2 + r3 + r4 + v1)
    assert result.counts["raw_rows"] == 5
    assert result.counts["kept"] == 1
    assert result.counts["missing_price"] == 4


def test_row_rule_invalid_fields() -> None:
    """Verify invalid timestamp, side, instrument_type, strike, lot_size, expiry."""
    r1 = _row(oid="ORD01", ts="invalid-ts")
    r2 = _row(oid="ORD02", side="HOLD")
    r3 = _row(oid="ORD03", inst="XX")
    r4 = _row(oid="ORD04", strike="-500")
    r5 = _row(oid="ORD05", expiry="bad-date")

    result = parse_orders(SAMPLE_HEADER + r1 + r2 + r3 + r4 + r5)
    assert result.counts["raw_rows"] == 5
    assert result.counts["kept"] == 0
    assert result.counts["invalid"] == 5

    field_msgs = [w.message for w in result.warnings if w.code == "invalid"]
    assert any("timestamp" in m for m in field_msgs)
    assert any("side" in m for m in field_msgs)
    assert any("instrument_type" in m for m in field_msgs)
    assert any("strike" in m for m in field_msgs)
    assert any("expiry" in m for m in field_msgs)


def test_row_rule_precedence() -> None:
    """Verify strict precedence: duplicate > rejected > missing_price > invalid."""
    # Row that is both rejected and missing price: counted as REJECTED (precedence 2)
    rej_missing = _row(oid="ORD01", price="", status="CANCELLED")
    res1 = parse_orders(SAMPLE_HEADER + rej_missing)
    assert res1.counts["rejected"] == 1
    assert res1.counts["missing_price"] == 0

    # Row that is duplicate of a rejected row: counted as DUPLICATE (precedence 1)
    res2 = parse_orders(SAMPLE_HEADER + rej_missing + rej_missing)
    assert res2.counts["rejected"] == 1
    assert res2.counts["duplicates"] == 1
    assert res2.counts["missing_price"] == 0

    # Row with missing price and invalid side: counted as MISSING_PRICE (precedence 3)
    missing_invalid = _row(oid="ORD02", side="BAD_SIDE", price="")
    res3 = parse_orders(SAMPLE_HEADER + missing_invalid)
    assert res3.counts["missing_price"] == 1
    assert res3.counts["invalid"] == 0


def test_naive_timestamp_gets_assumed_ist_once() -> None:
    """Verify naive timestamps trigger assumed_ist warning exactly once per file."""
    r1 = _row(oid="ORD01", ts="2024-10-01 09:20:00")
    r2 = _row(oid="ORD02", ts="2024-10-01 09:25:00")

    result = parse_orders(SAMPLE_HEADER + r1 + r2)
    assert result.counts["kept"] == 2

    ist_warnings = [w for w in result.warnings if w.code == "assumed_ist"]
    assert len(ist_warnings) == 1

    # Verify orders now have IST timezone (+05:30)
    for o in result.orders:
        assert o.timestamp.tzinfo is not None
        assert o.timestamp.utcoffset() == timedelta(hours=5, minutes=30)


def test_accepts_path_str_bytes_and_io(tmp_path: Path) -> None:
    """Verify parser accepts Path, file path str, bytes, and open file object."""
    csv_content = SAMPLE_HEADER + _row(oid="ORD01")
    file_path = tmp_path / "orders.csv"
    file_path.write_text(csv_content, encoding="utf-8")

    # 1. Path object
    r_path = parse_orders(file_path)
    assert len(r_path.orders) == 1

    # 2. File path str
    r_str = parse_orders(str(file_path))
    assert len(r_str.orders) == 1

    # 3. CSV content str
    r_content = parse_orders(csv_content)
    assert len(r_content.orders) == 1

    # 4. Bytes
    r_bytes = parse_orders(csv_content.encode("utf-8"))
    assert len(r_bytes.orders) == 1

    # 5. Open file object
    with open(file_path, encoding="utf-8") as f:
        r_io = parse_orders(f)
        assert len(r_io.orders) == 1

    # 6. BytesIO
    r_bio = parse_orders(BytesIO(csv_content.encode("utf-8")))
    assert len(r_bio.orders) == 1

    # 7. StringIO
    r_sio = parse_orders(StringIO(csv_content))
    assert len(r_sio.orders) == 1
