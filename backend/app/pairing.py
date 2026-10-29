"""FIFO Round-Trip Trade Matching module for TradeMirror.

Responsibility:
Consumes a sequence of Orders and pairs buy and sell executions using First-In-First-Out (FIFO)
accounting to produce closed round-trip Trade objects with deterministic P&L and duration metrics.

MATCHING RULES:
- Position key = (symbol, instrument_type, strike, expiry). Matching is isolated per key.
- A BUY opens a long position; a SELL opens a short position.
- Opposite-side orders close open lots in FIFO order (oldest lot closed first).
- Partial exits: an exit smaller than an open lot consumes part of the lot (is_partial_exit = True).
  An exit larger than an open lot consumes lots sequentially, emitting one Trade per matched slice.
- Add-ons: an order in the same direction while a position is already open creates a new lot
  (is_add_on = True).
- Position flips: an opposite order larger than total open volume closes all open lots and opens
  a new position in the opposite direction with the remainder.
- GROSS P&L ONLY (no brokerage, taxes, or charges):
    Long  = (exit_price - entry_price) * quantity
    Short = (entry_price - exit_price) * quantity
- Unclosed lots at data end are returned in open_positions, noted in anomalies, and never feed P&L.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, NamedTuple

from app.models import OpenPosition, Order, Trade

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class PositionKey(NamedTuple):
    """Unique identifier for an instrument position."""

    symbol: str
    instrument_type: str
    strike: float
    expiry: date


@dataclass
class OpenLot:
    """Internal mutable tracking of an open position lot."""

    order_id: str
    direction: str  # "LONG" or "SHORT"
    entry_time: datetime
    entry_price: float
    remaining_quantity: int
    initial_quantity: int
    lot_size: int
    is_add_on: bool
    trading_date: date


@dataclass
class PairingResult:
    """Result of FIFO order matching."""

    trades: list[Trade]
    open_positions: list[OpenPosition]
    anomalies: list[str]


def pair_orders(orders: list[Order]) -> PairingResult:
    """Match orders into closed round-trip trades using FIFO pairing."""
    # Ensure orders are strictly sorted by timestamp ascending, ties broken by order_id
    sorted_orders = sorted(orders, key=lambda o: (o.timestamp, o.order_id))

    # Active FIFO lot queues isolated by position key
    open_queues: dict[PositionKey, list[OpenLot]] = {}

    raw_trades: list[dict[str, Any]] = []
    anomalies: list[str] = []

    for order in sorted_orders:
        if order.status != "COMPLETE":
            continue

        key = PositionKey(
            symbol=order.symbol,
            instrument_type=order.instrument_type,
            strike=order.strike if order.strike is not None else 0.0,
            expiry=order.expiry if order.expiry is not None else date.min,
        )

        queue = open_queues.setdefault(key, [])

        order_side = order.side.upper()
        order_qty = order.quantity
        order_price = order.price
        order_time = order.timestamp

        order_trading_date = (
            order_time.astimezone(IST).date() if order_time.tzinfo else order_time.date()
        )

        # Case 1: No open lots for this instrument key -> open initial lot
        if not queue:
            direction = "LONG" if order_side == "BUY" else "SHORT"
            queue.append(
                OpenLot(
                    order_id=order.order_id,
                    direction=direction,
                    entry_time=order_time,
                    entry_price=order_price,
                    remaining_quantity=order_qty,
                    initial_quantity=order_qty,
                    lot_size=order.lot_size,
                    is_add_on=False,
                    trading_date=order_trading_date,
                )
            )
            continue

        current_direction = queue[0].direction

        # Case 2: Order is in the SAME direction as open lots -> Add-on lot
        if (current_direction == "LONG" and order_side == "BUY") or (
            current_direction == "SHORT" and order_side == "SELL"
        ):
            queue.append(
                OpenLot(
                    order_id=order.order_id,
                    direction=current_direction,
                    entry_time=order_time,
                    entry_price=order_price,
                    remaining_quantity=order_qty,
                    initial_quantity=order_qty,
                    lot_size=order.lot_size,
                    is_add_on=True,  # Lot opened while another lot is already open
                    trading_date=order_trading_date,
                )
            )
            continue

        # Case 3: Order is in the OPPOSITE direction -> Close open lots FIFO
        remaining_to_close = order_qty

        while remaining_to_close > 0 and queue:
            oldest_lot = queue[0]
            matched_qty = min(remaining_to_close, oldest_lot.remaining_quantity)

            # Did this exit leave the oldest lot partially open?
            is_partial_exit = matched_qty < oldest_lot.remaining_quantity

            # Calculate hold duration in minutes
            duration_secs = (order_time - oldest_lot.entry_time).total_seconds()
            hold_minutes = max(0.0, round(duration_secs / 60.0, 2))

            # Compute gross P&L
            if oldest_lot.direction == "LONG":
                gross_pnl = round((order_price - oldest_lot.entry_price) * matched_qty, 2)
            else:
                gross_pnl = round((oldest_lot.entry_price - order_price) * matched_qty, 2)

            raw_trades.append(
                {
                    "symbol": key.symbol,
                    "instrument_type": key.instrument_type,
                    "strike": key.strike,
                    "expiry": key.expiry,
                    "direction": oldest_lot.direction,
                    "entry_time": oldest_lot.entry_time,
                    "exit_time": order_time,
                    "entry_price": oldest_lot.entry_price,
                    "exit_price": order_price,
                    "quantity": matched_qty,
                    "lot_size": oldest_lot.lot_size,
                    "hold_minutes": hold_minutes,
                    "gross_pnl": gross_pnl,
                    "entry_order_id": oldest_lot.order_id,
                    "exit_order_id": order.order_id,
                    "is_partial_exit": is_partial_exit,
                    "is_add_on": oldest_lot.is_add_on,
                    "trading_date": oldest_lot.trading_date,
                }
            )

            oldest_lot.remaining_quantity -= matched_qty
            remaining_to_close -= matched_qty

            if oldest_lot.remaining_quantity == 0:
                queue.pop(0)

        # Case 4: Position flip (order was larger than open opposite volume)
        if remaining_to_close > 0:
            new_direction = "LONG" if order_side == "BUY" else "SHORT"
            queue.append(
                OpenLot(
                    order_id=order.order_id,
                    direction=new_direction,
                    entry_time=order_time,
                    entry_price=order_price,
                    remaining_quantity=remaining_to_close,
                    initial_quantity=remaining_to_close,
                    lot_size=order.lot_size,
                    is_add_on=False,
                    trading_date=order_trading_date,
                )
            )

    # Collect any unclosed lots remaining at period close
    open_positions: list[OpenPosition] = []
    for key, queue in open_queues.items():
        for lot in queue:
            if lot.remaining_quantity > 0:
                open_pos = OpenPosition(
                    symbol=key.symbol,
                    instrument_type=key.instrument_type,
                    strike=key.strike,
                    expiry=key.expiry,
                    direction=lot.direction,
                    quantity=lot.remaining_quantity,
                    lot_size=lot.lot_size,
                    entry_price=lot.entry_price,
                    entry_time=lot.entry_time,
                    entry_order_id=lot.order_id,
                    is_add_on=lot.is_add_on,
                )
                open_positions.append(open_pos)
                entry_str = open_pos.entry_time.isoformat()
                anomalies.append(
                    f"Open position at end of period: {open_pos.direction} {open_pos.quantity} "
                    f"{open_pos.symbol} entered at {entry_str} ({open_pos.entry_order_id})"
                )

    # Sort closed trades deterministically by exit_time, entry_time, entry_order_id
    raw_trades.sort(
        key=lambda t: (
            t["exit_time"],
            t["entry_time"],
            t["entry_order_id"],
        )
    )

    # Assign deterministic trade_id P0001, P0002...
    final_trades: list[Trade] = []
    for idx, t in enumerate(raw_trades, start=1):
        trade_id = f"P{idx:04d}"
        trade = Trade(
            trade_id=trade_id,
            symbol=t["symbol"],
            instrument_type=t["instrument_type"],
            strike=t["strike"],
            expiry=t["expiry"],
            direction=t["direction"],
            entry_time=t["entry_time"],
            exit_time=t["exit_time"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            quantity=t["quantity"],
            lot_size=t["lot_size"],
            hold_minutes=t["hold_minutes"],
            gross_pnl=t["gross_pnl"],
            entry_order_id=t["entry_order_id"],
            exit_order_id=t["exit_order_id"],
            is_partial_exit=t["is_partial_exit"],
            is_add_on=t["is_add_on"],
            trading_date=t["trading_date"],
        )
        final_trades.append(trade)

    return PairingResult(
        trades=final_trades,
        open_positions=open_positions,
        anomalies=anomalies,
    )
