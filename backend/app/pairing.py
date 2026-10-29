"""FIFO Round-Trip Trade Matching module.

Responsibility:
Consumes a sorted sequence of Orders and pairs buy and sell executions using
First-In-First-Out (FIFO) accounting to produce closed round-trip Trade objects with
deterministic P&L and duration metrics.
"""

from app.models import Order, Trade


def pair_orders_fifo(orders: list[Order]) -> list[Trade]:
    """Pair orders into closed round-trip trades using FIFO matching."""
    return []
