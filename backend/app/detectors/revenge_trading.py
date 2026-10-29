"""Revenge Trading habit detector.

Responsibility:
Detect rapid re-entry following a losing trade with increased position size.

Formula and Definitions:
Uses gross P&L only (charges are excluded). Trades with gross_pnl == 0 are not losses.

Definitions:
- Closing event: All Trade slices sharing the same exit_order_id, treated as ONE event
  with pnl = sum of slice pnls, quantity = sum of slice quantities, and exit_time = their exit_time.
- Entry event: All Trade slices sharing the same entry_order_id, treated as one entry
  with quantity = sum of slice quantities, entry_time = their entry_time. Add-on entries
  (is_add_on = True) are skipped; those belong to the averaging_down detector.
- Prior event: For any entry event, the closing event with the latest exit_time that is
  <= the entry's entry_time (ties broken by exit_order_id). If no such closing event exists,
  the entry is ignored.

Detection Criteria:
1. An entry is FLAGGED when all of the following hold:
   a) prior event pnl < 0
   b) 0 <= entry_time - prior exit_time <= WINDOW_MINUTES (15.0)
   c) entry quantity >= SIZE_MULTIPLE (1.5) * prior event quantity
2. Require len(flagged entries) >= MIN_FLAGGED (3), else return None.
3. flagged_trade_ids = sorted list of Trade.trade_id for every slice belonging to a flagged entry.
4. estimated_cost_inr = max(0.0, -(sum of gross_pnl over those slices)). This is the net loss
   on revenge trades (winners offset losers). If <= 0, return None.
5. confidence = min(1.0, flagged_entries / 8.0), rounded to 2 decimal places.
6. metrics = {
       "eligible_entries": count of entries whose prior event was a loss within WINDOW_MINUTES,
       "flagged_entries": count of flagged entries,
       "avg_size_multiple": mean of (entry qty / prior qty) over flagged entries,
       "avg_gap_minutes": mean of gap minutes over flagged entries,
       "flagged_net_pnl_inr": net gross P&L of flagged trade slices,
       "revenge_win_rate": share of flagged entries that were profitable (net pnl > 0),
   }
"""

from typing import Any

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade

WINDOW_MINUTES: float = 15.0
SIZE_MULTIPLE: float = 1.5
MIN_FLAGGED: int = 3
CONFIDENCE_SATURATION_ENTRIES: float = 8.0


class RevengeTradingDetector(BaseDetector):
    """Detects rapid re-entry with increased size following a loss."""

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for revenge trading patterns.

        Args:
            trades: List of matched round-trip Trade objects.

        Returns:
            HabitResult if revenge trading pattern is detected, None otherwise.
        """
        if not trades:
            return None

        # Step 1: Aggregate Trade slices into Closing Events by exit_order_id
        closing_events_by_id: dict[str, dict[str, Any]] = {}
        for t in trades:
            if t.exit_order_id not in closing_events_by_id:
                closing_events_by_id[t.exit_order_id] = {
                    "exit_order_id": t.exit_order_id,
                    "exit_time": t.exit_time,
                    "quantity": 0,
                    "gross_pnl": 0.0,
                }
            closing_events_by_id[t.exit_order_id]["quantity"] += t.quantity
            closing_events_by_id[t.exit_order_id]["gross_pnl"] += t.gross_pnl

        closings = list(closing_events_by_id.values())

        # Step 2: Aggregate Trade slices into Entry Events by entry_order_id
        entry_events_by_id: dict[str, dict[str, Any]] = {}
        for t in trades:
            if t.entry_order_id not in entry_events_by_id:
                entry_events_by_id[t.entry_order_id] = {
                    "entry_order_id": t.entry_order_id,
                    "entry_time": t.entry_time,
                    "quantity": 0,
                    "gross_pnl": 0.0,
                    "is_add_on": False,
                    "slices": [],
                }
            entry_events_by_id[t.entry_order_id]["quantity"] += t.quantity
            entry_events_by_id[t.entry_order_id]["gross_pnl"] += t.gross_pnl
            if t.is_add_on:
                entry_events_by_id[t.entry_order_id]["is_add_on"] = True
            entry_events_by_id[t.entry_order_id]["slices"].append(t)

        sorted_entries = sorted(
            entry_events_by_id.values(),
            key=lambda e: (e["entry_time"], e["entry_order_id"]),
        )

        # Step 3: Evaluate each entry against its prior closing event
        eligible_entries = 0
        flagged_entries: list[dict[str, Any]] = []
        flagged_slices: list[Trade] = []

        for entry in sorted_entries:
            # Skip any entry that is an add-on
            if entry["is_add_on"]:
                continue

            # Prior closing event with latest exit_time <= entry_time (ties broken by exit_order_id)
            candidates = [c for c in closings if c["exit_time"] <= entry["entry_time"]]
            if not candidates:
                continue

            prior = max(candidates, key=lambda c: (c["exit_time"], c["exit_order_id"]))

            # Check gap in minutes
            gap_seconds = (entry["entry_time"] - prior["exit_time"]).total_seconds()
            gap_minutes = gap_seconds / 60.0

            # Condition a & b: prior event was a loss and within WINDOW_MINUTES
            if prior["gross_pnl"] < 0 and 0.0 <= gap_minutes <= WINDOW_MINUTES:
                eligible_entries += 1
                size_mult = entry["quantity"] / prior["quantity"]

                # Condition c: entry quantity >= SIZE_MULTIPLE * prior quantity
                if entry["quantity"] >= SIZE_MULTIPLE * prior["quantity"]:
                    flagged_entries.append(
                        {
                            "entry": entry,
                            "prior": prior,
                            "gap_minutes": gap_minutes,
                            "size_multiple": size_mult,
                        }
                    )
                    flagged_slices.extend(entry["slices"])

        # Step 4: Require minimum flagged count
        if len(flagged_entries) < MIN_FLAGGED:
            return None

        # Step 5: Calculate estimated cost (net loss on revenge trades)
        flagged_net_pnl = sum(s.gross_pnl for s in flagged_slices)
        estimated_cost_inr = max(0.0, -flagged_net_pnl)
        if estimated_cost_inr <= 0.0:
            return None

        # Step 6: Confidence calculation
        confidence = round(min(1.0, len(flagged_entries) / CONFIDENCE_SATURATION_ENTRIES), 2)

        # Step 7: Metrics and formula note
        avg_size_multiple = sum(f["size_multiple"] for f in flagged_entries) / len(flagged_entries)
        avg_gap_minutes = sum(f["gap_minutes"] for f in flagged_entries) / len(flagged_entries)
        profitable_entries = sum(1 for f in flagged_entries if f["entry"]["gross_pnl"] > 0)
        revenge_win_rate = profitable_entries / len(flagged_entries)

        metrics = {
            "eligible_entries": eligible_entries,
            "flagged_entries": len(flagged_entries),
            "avg_size_multiple": round(avg_size_multiple, 2),
            "avg_gap_minutes": round(avg_gap_minutes, 2),
            "flagged_net_pnl_inr": round(flagged_net_pnl, 2),
            "revenge_win_rate": round(revenge_win_rate, 2),
        }

        formula_note = (
            f"After taking a loss, you re-entered within {WINDOW_MINUTES:.0f} minutes with at "
            f"least {SIZE_MULTIPLE:.1f}x your previous position size on {len(flagged_entries)} "
            f"occasions (out of {eligible_entries} re-entries following a loss within "
            f"{WINDOW_MINUTES:.0f} minutes). These revenge trades averaged "
            f"{metrics['avg_size_multiple']:.2f}x the prior size with an average gap of "
            f"{metrics['avg_gap_minutes']:.1f} minutes, resulting in a net loss of "
            f"₹{estimated_cost_inr:,.2f} (win rate of {metrics['revenge_win_rate'] * 100:.0f}%)."
        )

        flagged_trade_ids = sorted(t.trade_id for t in flagged_slices)

        return HabitResult(
            key="revenge_trading",
            name="Re-entering fast after a loss with a bigger size",
            flagged_trade_ids=flagged_trade_ids,
            estimated_cost_inr=round(estimated_cost_inr, 2),
            confidence=confidence,
            metrics=metrics,
            formula_note=formula_note,
        )
