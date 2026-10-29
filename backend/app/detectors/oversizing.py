"""Oversizing habit detector.

Responsibility:
Detect trades where the trader takes a much bigger position than usual (> 2× their
median trade size in lots) immediately after a run of consecutive wins or losses.

Formula and Definitions:
Uses gross P&L only (charges are excluded). Trades with gross_pnl == 0 break a
streak and are neither winners nor losers.

Definitions:
- Entry event: all Trade slices sharing the same entry_order_id treated as ONE entry.
  size_lots = sum(quantity / lot_size) over slices, pnl = sum of slice pnls.
  Add-on entries (is_add_on = True on any slice) are skipped entirely; they belong
  to the averaging_down detector.
- Closing event: all Trade slices sharing the same exit_order_id treated as one
  event. pnl = sum of slice pnls. Closing events are ordered by (exit_time,
  exit_order_id) for streak computation.
- Streak before an entry: take the last STREAK_LEN (2) closing events whose
  exit_time <= entry_time. It is a win streak if all have pnl > 0; a loss streak if
  all have pnl < 0. A zero-pnl closing event breaks the streak. Fewer than
  STREAK_LEN prior closing events means no streak for that entry.

Detection Criteria:
1. Require at least MIN_ENTRIES (20) entry events, else return None.
2. median_lots = median of size_lots over all entry events.
3. An entry is FLAGGED when:
   - size_lots > SIZE_MULTIPLE (2.0) * median_lots  (strictly greater), AND
   - it follows a streak of STREAK_LEN (2) consecutive wins or losses.
4. Require len(flagged) >= MIN_FLAGGED (3), else return None.
5. flagged_trade_ids = Trade.trade_id of every slice of a flagged entry, sorted.
6. estimated_cost_inr = sum over flagged entries of:
       max(0, -entry_pnl) * (1 - median_lots / size_lots)
   This estimates the extra loss attributable to the oversized position, assuming
   P&L scales linearly with size (i.e. a normal-size trade would have lost
   proportionally less). Rounded to 2 decimals. If total <= 0, return None.
7. confidence = min(1.0, flagged_entries / 8.0), rounded to 2 decimal places.
8. metrics = {
       "n_entries": total entry events (excluding add-ons),
       "median_lots": median lots across all entries,
       "flagged_entries": count of flagged entries,
       "avg_size_multiple": mean of (size_lots / median_lots) over flagged entries,
       "after_win_streak": count of flagged entries following a win streak,
       "after_loss_streak": count of flagged entries following a loss streak,
       "flagged_net_pnl_inr": net gross P&L of all slices in flagged entries,
       "flagged_gross_loss_inr": sum of max(0, -entry_pnl) for flagged entries,
   }
9. name = "Betting much bigger after a streak"
10. formula_note: one plain paragraph with actual numbers filled in.
"""

import statistics
from typing import Any

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade, aggregate_lots

# ── Named module constants ────────────────────────────────────────────────────
MIN_ENTRIES: int = 20
SIZE_MULTIPLE: float = 2.0
STREAK_LEN: int = 2
MIN_FLAGGED: int = 3
CONFIDENCE_SATURATION_ENTRIES: float = 8.0


class OversizingDetector(BaseDetector):
    """Detects position sizing > 2× median lots following a 2+ consecutive win/loss streak."""

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for oversized positions following win/loss streaks.

        Args:
            trades: List of matched round-trip Trade objects (closed positions only).

        Returns:
            HabitResult if the oversizing pattern is detected, None otherwise.
        """
        if not trades:
            return None

        # ── Step 1: Aggregate closing events by exit_order_id ────────────────
        # Collect slices per closing event; compute pnl; record exit_time.
        closing_slices: dict[str, list[Trade]] = {}
        closing_pnl: dict[str, float] = {}
        closing_exit_time: dict[str, Any] = {}

        for t in trades:
            closing_slices.setdefault(t.exit_order_id, []).append(t)
            closing_pnl[t.exit_order_id] = closing_pnl.get(t.exit_order_id, 0.0) + t.gross_pnl
            closing_exit_time[t.exit_order_id] = t.exit_time  # same for all slices of one exit

        # Sort closing events by (exit_time, exit_order_id) for determinism
        sorted_closings: list[tuple[Any, str, float]] = sorted(
            [(closing_exit_time[eid], eid, closing_pnl[eid]) for eid in closing_pnl],
            key=lambda x: (x[0], x[1]),
        )
        # List of (exit_time, exit_order_id, pnl)

        # ── Step 2: Aggregate entry events by entry_order_id ─────────────────
        entry_slices: dict[str, list[Trade]] = {}
        entry_pnl: dict[str, float] = {}
        entry_time_map: dict[str, Any] = {}
        entry_is_addon: dict[str, bool] = {}

        for t in trades:
            entry_slices.setdefault(t.entry_order_id, []).append(t)
            entry_pnl[t.entry_order_id] = entry_pnl.get(t.entry_order_id, 0.0) + t.gross_pnl
            entry_time_map[t.entry_order_id] = t.entry_time
            if t.is_add_on:
                entry_is_addon[t.entry_order_id] = True

        # Skip add-on entries
        valid_entry_ids = [
            eid for eid in entry_slices if not entry_is_addon.get(eid, False)
        ]

        # Sort entries by (entry_time, entry_order_id) for determinism
        sorted_entries = sorted(
            valid_entry_ids,
            key=lambda eid: (entry_time_map[eid], eid),
        )

        # ── Step 3: Require minimum entry count ───────────────────────────────
        n_entries = len(sorted_entries)
        if n_entries < MIN_ENTRIES:
            return None

        # ── Step 4: Compute lots per entry and median ─────────────────────────
        entry_lots: dict[str, float] = {
            eid: aggregate_lots(entry_slices[eid]) for eid in sorted_entries
        }
        all_lots = [entry_lots[eid] for eid in sorted_entries]
        median_lots = statistics.median(all_lots)

        # ── Step 5: Identify streak before each entry and flag ────────────────
        flagged: list[dict[str, Any]] = []
        flagged_slices: list[Trade] = []

        for eid in sorted_entries:
            e_time = entry_time_map[eid]
            e_lots = entry_lots[eid]

            # Size gate: strictly greater than SIZE_MULTIPLE * median_lots
            if not (e_lots > SIZE_MULTIPLE * median_lots):
                continue

            # Find the last STREAK_LEN closing events with exit_time <= entry_time
            prior_closings = [
                (et, eoid, pnl)
                for (et, eoid, pnl) in sorted_closings
                if et <= e_time
            ]
            if len(prior_closings) < STREAK_LEN:
                continue

            last_n = prior_closings[-STREAK_LEN:]
            pnls = [pnl for (_, _, pnl) in last_n]

            # All must be strictly positive (win streak) or strictly negative (loss streak)
            # Zero breaks the streak
            is_win_streak = all(p > 0 for p in pnls)
            is_loss_streak = all(p < 0 for p in pnls)

            if not (is_win_streak or is_loss_streak):
                continue

            # Entry is flagged
            entry_pnl_val = entry_pnl[eid]
            flagged.append({
                "eid": eid,
                "size_lots": e_lots,
                "pnl": entry_pnl_val,
                "size_multiple": e_lots / median_lots,
                "after_win_streak": is_win_streak,
                "after_loss_streak": is_loss_streak,
            })
            flagged_slices.extend(entry_slices[eid])

        # ── Step 6: Require minimum flagged count ─────────────────────────────
        if len(flagged) < MIN_FLAGGED:
            return None

        # ── Step 7: Compute estimated cost ────────────────────────────────────
        # Extra loss = max(0, -pnl) * (1 - median_lots / size_lots)
        # This is the portion of the loss attributable to the excess size.
        # Assumes P&L scales linearly with size.
        total_cost = sum(
            max(0.0, -f["pnl"]) * (1.0 - median_lots / f["size_lots"])
            for f in flagged
        )
        total_cost = round(total_cost, 2)
        if total_cost <= 0.0:
            return None

        # ── Step 8: Confidence ────────────────────────────────────────────────
        confidence = round(
            min(1.0, len(flagged) / CONFIDENCE_SATURATION_ENTRIES), 2
        )

        # ── Step 9: Metrics ───────────────────────────────────────────────────
        flagged_net_pnl = sum(s.gross_pnl for s in flagged_slices)
        flagged_gross_loss = sum(max(0.0, -f["pnl"]) for f in flagged)
        avg_size_multiple = sum(f["size_multiple"] for f in flagged) / len(flagged)
        after_win = sum(1 for f in flagged if f["after_win_streak"])
        after_loss = sum(1 for f in flagged if f["after_loss_streak"])

        metrics: dict[str, Any] = {
            "n_entries": n_entries,
            "median_lots": round(median_lots, 2),
            "flagged_entries": len(flagged),
            "avg_size_multiple": round(avg_size_multiple, 2),
            "after_win_streak": after_win,
            "after_loss_streak": after_loss,
            "flagged_net_pnl_inr": round(flagged_net_pnl, 2),
            "flagged_gross_loss_inr": round(flagged_gross_loss, 2),
        }

        # ── Step 10: Formula note ─────────────────────────────────────────────
        formula_note = (
            f"On {len(flagged)} occasions after {STREAK_LEN}+ consecutive wins or losses, "
            f"you entered with a position more than {SIZE_MULTIPLE:.0f}× your typical size "
            f"(median: {median_lots:.1f} lot{'s' if median_lots != 1 else ''}, flagged average: "
            f"{avg_size_multiple:.1f}× median). "
            f"{after_win} followed a win streak and {after_loss} followed a loss streak. "
            f"These outsized bets lost ₹{flagged_gross_loss:,.2f} in total; "
            f"the estimated extra cost from taking a bigger-than-normal position is "
            f"₹{total_cost:,.2f} (assuming P&L scales linearly with size)."
        )

        flagged_trade_ids = sorted(s.trade_id for s in flagged_slices)

        return HabitResult(
            key="oversizing",
            name="Betting much bigger after a streak",
            flagged_trade_ids=flagged_trade_ids,
            estimated_cost_inr=total_cost,
            confidence=confidence,
            metrics=metrics,
            formula_note=formula_note,
        )
