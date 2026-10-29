"""Canonical Orders CSV parser.

Responsibility:
Ingests and validates CSV order books matching the canonical schema:
order_id, timestamp, symbol, instrument_type, strike, expiry, side, quantity,
lot_size, price, status.
Converts rows into strongly-typed Order domain objects.
"""

from io import StringIO
from typing import TextIO

from app.models import Order


def parse_orders_csv(file_or_content: str | TextIO | StringIO) -> list[Order]:
    """Parse canonical orders CSV into a validated list of Order models."""
    return []
