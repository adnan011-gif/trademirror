"""Core domain dataclasses for orders, paired round-trip trades, open positions, and habits."""

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
    instrument_type: str
    strike: float
    expiry: date
    direction: str  # "LONG" or "SHORT"
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: int
    lot_size: int
    hold_minutes: float
    gross_pnl: float
    entry_order_id: str
    exit_order_id: str
    is_partial_exit: bool
    is_add_on: bool
    trading_date: date

    @property
    def pnl_inr(self) -> float:
        """Alias for gross_pnl in INR."""
        return self.gross_pnl

    @property
    def order_ids(self) -> list[str]:
        """List of order IDs involved in this trade."""
        return [self.entry_order_id, self.exit_order_id]

    @property
    def trade_lots(self) -> float:
        """Position size expressed in lots (quantity / lot_size).

        Use this — not raw quantity — when comparing sizes across different
        instruments that have different lot sizes (e.g. NIFTY=75 vs BANKNIFTY=35).
        """
        return self.quantity / self.lot_size


def aggregate_lots(slices: "list[Trade]") -> float:
    """Return the total position size in lots for a group of Trade slices.

    Each slice contributes its own lots (quantity / lot_size) so that
    cross-instrument comparisons remain meaningful even when lot sizes differ.

    Args:
        slices: One or more Trade objects that share an entry_order_id or
                exit_order_id and represent the same logical position event.

    Returns:
        Sum of (quantity / lot_size) over all slices, as a float.
    """
    return sum(t.trade_lots for t in slices)


@dataclass(frozen=True)
class OpenPosition:
    """Represents an unclosed position lot remaining at the end of the order history."""

    symbol: str
    instrument_type: str
    strike: float
    expiry: date
    direction: str  # "LONG" or "SHORT"
    quantity: int
    lot_size: int
    entry_price: float
    entry_time: datetime
    entry_order_id: str
    is_add_on: bool


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
