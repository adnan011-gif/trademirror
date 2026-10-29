"""Averaging Down habit detector.

Responsibility:
Detect behavior where the trader adds to a position that is already losing,
hoping to average the price down.

Gross P&L only:
All P&L calculations in this detector use gross P&L only. Brokerage, STT, exchange
turnover fees, GST, and SEBI charges are excluded.

Formula and Definitions:
1. Add-on entry event:
   All Trade slices sharing the same entry_order_id where is_add_on = True, treated
   as ONE event (quantity = sum of slice quantities, pnl = sum of slice gross_pnl;
   entry_price is uniform across slices).
2. Existing position at the add-on's entry_time:
   All other slices sharing the same position key (symbol, instrument_type, strike,
   expiry) and the same direction, with entry_time before the add-on's entry_time
   (ties broken by entry_order_id < add_on.entry_order_id) AND exit_time strictly after
   the add-on's entry_time.
   Existing average entry = quantity-weighted mean of those qualifying slices' entry_price:
       sum(slice.quantity * slice.entry_price) / sum(slice.quantity)
   If no qualifying slices exist, the add-on is not evaluated.
3. Underwater add-on:
   - For LONG: add-on entry_price < existing average entry (strictly).
   - For SHORT: add-on entry_price > existing average entry (strictly).
   Equal price or adding to a winning position (pyramiding) is NOT flagged.
4. Flagging and thresholds:
   - len(flagged_entries) >= MIN_FLAGGED (3), else return None.
   - estimated_cost_inr = max(0.0, -sum(flagged_slice_gross_pnl)). Net loss on the add-on
     legs, so winning add-ons offset losing ones. If estimated_cost_inr <= 0, return None.
   - confidence = min(1.0, flagged_entries / CONFIDENCE_DIVISOR), rounded to 2.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade

MIN_FLAGGED: int = 3
CONFIDENCE_DIVISOR: int = 6


@dataclass(frozen=True)
class _AddOnEntryEvent:
    """Aggregated representation of an add-on entry event."""

    entry_order_id: str
    slices: list[Trade]
    symbol: str
    instrument_type: str
    strike: float
    expiry: object
    direction: str
    entry_time: object
    entry_price: float
    quantity: int
    gross_pnl: float


class AveragingDownDetector(BaseDetector):
    """Detects adding capital to underwater (losing) open positions."""

    key = "averaging_down"

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for averaging down patterns.

        Args:
            trades: Paired round-trip trades.

        Returns:
            HabitResult if habit is detected and net cost > 0, else None.
        """
        if not trades:
            return None

        # Group all trades by entry_order_id to determine entry events
        by_entry_id: dict[str, list[Trade]] = {}
        for t in trades:
            by_entry_id.setdefault(t.entry_order_id, []).append(t)

        n_entries = len(by_entry_id)

        # Collect add-on entry events
        addon_events: list[_AddOnEntryEvent] = []
        for eoid, slices in by_entry_id.items():
            if not slices[0].is_add_on:
                continue
            first = slices[0]
            total_qty = sum(s.quantity for s in slices)
            total_pnl = sum(s.gross_pnl for s in slices)
            addon_events.append(
                _AddOnEntryEvent(
                    entry_order_id=eoid,
                    slices=slices,
                    symbol=first.symbol,
                    instrument_type=first.instrument_type,
                    strike=first.strike,
                    expiry=first.expiry,
                    direction=first.direction,
                    entry_time=first.entry_time,
                    entry_price=first.entry_price,
                    quantity=total_qty,
                    gross_pnl=total_pnl,
                )
            )

        add_on_entries = len(addon_events)
        if add_on_entries < MIN_FLAGGED:
            return None

        # Evaluate each add-on against the existing open position at its entry_time
        flagged_entries: list[
            tuple[_AddOnEntryEvent, float, float]
        ] = []  # (event, avg_entry, drop_pct)

        for addon in addon_events:
            pos_key = (addon.symbol, addon.instrument_type, addon.strike, addon.expiry)

            # Find existing open position slices:
            # - Same position key
            # - Same direction
            # - Entered before add-on entry_time (ties broken by entry_order_id)
            # - Exited strictly after add-on entry_time
            existing_slices = [
                t
                for t in trades
                if (t.symbol, t.instrument_type, t.strike, t.expiry) == pos_key
                and t.direction == addon.direction
                and (
                    t.entry_time < addon.entry_time
                    or (
                        t.entry_time == addon.entry_time and t.entry_order_id < addon.entry_order_id
                    )
                )
                and t.exit_time > addon.entry_time
            ]

            if not existing_slices:
                # No qualifying open position slices at this time; skip
                continue

            existing_qty = sum(s.quantity for s in existing_slices)
            if existing_qty <= 0:
                continue

            avg_entry_price = (
                sum(s.quantity * s.entry_price for s in existing_slices) / existing_qty
            )

            # Underwater check:
            # LONG: add-on entry_price < existing average entry (strictly)
            # SHORT: add-on entry_price > existing average entry (strictly)
            is_underwater = (
                (addon.entry_price < avg_entry_price)
                if addon.direction == "LONG"
                else (addon.entry_price > avg_entry_price)
            )

            if is_underwater:
                if addon.direction == "LONG":
                    drop_pct = (avg_entry_price - addon.entry_price) / avg_entry_price * 100.0
                else:
                    drop_pct = (addon.entry_price - avg_entry_price) / avg_entry_price * 100.0

                flagged_entries.append((addon, avg_entry_price, drop_pct))

        if len(flagged_entries) < MIN_FLAGGED:
            return None

        # Slices belonging to flagged add-on entries
        flagged_slices: list[Trade] = []
        for event, _, _ in flagged_entries:
            flagged_slices.extend(event.slices)

        flagged_trade_ids = sorted(s.trade_id for s in flagged_slices)
        flagged_net_pnl_inr = round(sum(s.gross_pnl for s in flagged_slices), 2)

        # Net loss on the add-on legs (winning add-ons offset losing ones)
        estimated_cost_inr = round(max(0.0, -flagged_net_pnl_inr), 2)
        if estimated_cost_inr <= 0.0:
            return None

        confidence = round(min(1.0, len(flagged_entries) / CONFIDENCE_DIVISOR), 2)

        avg_drop_pct = round(sum(drop for _, _, drop in flagged_entries) / len(flagged_entries), 2)
        profitable_addons = sum(1 for event, _, _ in flagged_entries if event.gross_pnl > 0)
        add_on_win_rate = round(profitable_addons / len(flagged_entries), 2)

        metrics = {
            "n_entries": n_entries,
            "add_on_entries": add_on_entries,
            "flagged_entries": len(flagged_entries),
            "avg_drop_pct": avg_drop_pct,
            "flagged_net_pnl_inr": flagged_net_pnl_inr,
            "add_on_win_rate": add_on_win_rate,
        }

        formula_note = (
            f"You added to an already losing position {len(flagged_entries)} times across "
            f"{add_on_entries} total add-ons (average drop: {avg_drop_pct:.1f}% below your "
            f"original entry). Only {add_on_win_rate * 100:.0f}% of these add-ons ended "
            f"profitable, resulting in an estimated net loss of ₹{estimated_cost_inr:,.2f} "
            f"on the additional lots."
        )

        return HabitResult(
            key=self.key,
            name="Adding to a losing position",
            flagged_trade_ids=flagged_trade_ids,
            estimated_cost_inr=estimated_cost_inr,
            confidence=confidence,
            metrics=metrics,
            formula_note=formula_note,
        )
