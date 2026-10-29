"""Core domain dataclasses for orders, paired round-trip trades, and habits."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class Order:
    """Represents a single order from the broker order log."""

    order_id: str
    timestamp: datetime
    symbol: str
    instrument_type: str
    strike: float | None
    expiry: date | None
    side: str
    quantity: int
    lot_size: int
    price: float
    status: str


@dataclass(frozen=True)
class Trade:
    """Represents a matched round-trip trade produced by FIFO pairing."""

    trade_id: str
    symbol: str
    entry_time: datetime
    exit_time: datetime
    duration_minutes: float
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    pnl_inr: float
    order_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Habit:
    """Represents an extracted high-cost behavioral habit."""

    key: str
    name: str
    estimated_cost_inr: float
    evidence_trade_ids: list[str]
    explanation: str
    next_month_rule: str
    confidence: float
    metrics: dict[str, Any] = field(default_factory=dict)
