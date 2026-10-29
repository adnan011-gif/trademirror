"""Overtrading habit detector.

Responsibility:
Detect trading days where trade frequency spikes significantly above the trader's median baseline.

Gross P&L Only:
Uses gross P&L only. Real overtrading cost also includes brokerage, STT, exchange turnover fees,
and GST, which we do not model here; this estimated cost is therefore a conservative lower bound.

Definitions:
- Entry event: All Trade slices sharing the same entry_order_id, treated as ONE trade taken.
  Add-on entries (is_add_on = True) are skipped; those belong to the averaging_down detector.
- Day: Trade.trading_date (IST calendar date of entry).
- daily_count[day]: Number of distinct entry events on that day. Only days with at least one
  entry event are included.

Formula:
1. Require at least MIN_DAYS (10) distinct trading days, else return None.
2. median_daily = median of daily_count over all days present.
3. A day is a SPIKE DAY when daily_count > SPIKE_MULTIPLE (2.0) * median_daily (strictly greater).
4. Require at least MIN_SPIKE_DAYS (2) spike days, else return None.
5. keep_n = ceil(median_daily). On each spike day, order that day's entry events by
   (entry_time, entry_order_id); the first keep_n are considered normal session trades,
   and the remaining entries are classified as EXCESS.
6. flagged_trade_ids = Trade.trade_id of every slice belonging to an excess entry, sorted.
7. estimated_cost_inr = max(0.0, -(sum of gross_pnl over flagged slices)). Net loss, so winning
   excess trades offset losing ones. If <= 0, return None.
8. confidence = min(1.0, spike_days / 4.0), rounded to 2 decimal places.
9. metrics = {
       "n_days": count of active trading days,
       "median_daily_trades": median daily trade count,
       "spike_days": sorted list of ISO date strings for spike days,
       "spike_day_count": number of spike days,
       "excess_trades": count of excess entry events,
       "excess_net_pnl_inr": net gross P&L of flagged excess trade slices,
       "excess_win_rate": share of excess entry events that were profitable (gross_pnl > 0),
       "avg_trades_on_spike_days": average daily entries on spike days,
   }
"""

import math
import statistics
from datetime import date
from typing import Any

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade

MIN_DAYS: int = 10
SPIKE_MULTIPLE: float = 2.0
MIN_SPIKE_DAYS: int = 2
CONFIDENCE_SATURATION_DAYS: float = 4.0


class OvertradingDetector(BaseDetector):
    """Detects high-frequency session spikes exceeding sustainable activity levels."""

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for overtrading patterns across active trading days.

        Args:
            trades: List of matched round-trip Trade objects.

        Returns:
            HabitResult if overtrading habit is detected, None otherwise.
        """
        if not trades:
            return None

        # Step 1: Aggregate Trade slices into Entry Events by entry_order_id
        entry_events_by_id: dict[str, dict[str, Any]] = {}
        for t in trades:
            if t.entry_order_id not in entry_events_by_id:
                entry_events_by_id[t.entry_order_id] = {
                    "entry_order_id": t.entry_order_id,
                    "entry_time": t.entry_time,
                    "trading_date": t.trading_date,
                    "gross_pnl": 0.0,
                    "is_add_on": False,
                    "slices": [],
                }
            entry_events_by_id[t.entry_order_id]["gross_pnl"] += t.gross_pnl
            if t.is_add_on:
                entry_events_by_id[t.entry_order_id]["is_add_on"] = True
            entry_events_by_id[t.entry_order_id]["slices"].append(t)

        # Step 2: Filter out add-ons and group entry events by trading_date
        entries_by_day: dict[date, list[dict[str, Any]]] = {}
        for entry in entry_events_by_id.values():
            if entry["is_add_on"]:
                continue
            day = entry["trading_date"]
            entries_by_day.setdefault(day, []).append(entry)

        # Step 3: Require at least MIN_DAYS distinct days
        if len(entries_by_day) < MIN_DAYS:
            return None

        # Step 4: Calculate median daily entry events
        daily_counts = {day: len(entries) for day, entries in entries_by_day.items()}
        median_daily = float(statistics.median(daily_counts.values()))

        # Step 5: Identify spike days (daily_count > SPIKE_MULTIPLE * median_daily)
        spike_threshold = SPIKE_MULTIPLE * median_daily
        spike_days = sorted(
            [day for day, count in daily_counts.items() if count > spike_threshold]
        )

        if len(spike_days) < MIN_SPIKE_DAYS:
            return None

        # Step 6: Identify excess trades on spike days
        keep_n = math.ceil(median_daily)
        excess_entries: list[dict[str, Any]] = []
        flagged_slices: list[Trade] = []

        for day in spike_days:
            day_entries = sorted(
                entries_by_day[day],
                key=lambda e: (e["entry_time"], e["entry_order_id"]),
            )
            # The first keep_n entries are normal session trades, the rest are excess
            day_excess = day_entries[keep_n:]
            excess_entries.extend(day_excess)
            for entry in day_excess:
                flagged_slices.extend(entry["slices"])

        if not excess_entries:
            return None

        # Step 7: Calculate net cost on excess trades
        excess_net_pnl = sum(s.gross_pnl for s in flagged_slices)
        estimated_cost_inr = max(0.0, -excess_net_pnl)
        if estimated_cost_inr <= 0.0:
            return None

        # Step 8: Confidence calculation
        confidence = round(min(1.0, len(spike_days) / CONFIDENCE_SATURATION_DAYS), 2)

        # Step 9: Assemble metrics
        profitable_excess = sum(1 for e in excess_entries if e["gross_pnl"] > 0)
        excess_win_rate = profitable_excess / len(excess_entries)
        avg_trades_on_spike = sum(daily_counts[d] for d in spike_days) / len(spike_days)

        metrics = {
            "n_days": len(entries_by_day),
            "median_daily_trades": round(median_daily, 2),
            "spike_days": [d.isoformat() for d in spike_days],
            "spike_day_count": len(spike_days),
            "excess_trades": len(excess_entries),
            "excess_net_pnl_inr": round(excess_net_pnl, 2),
            "excess_win_rate": round(excess_win_rate, 2),
            "avg_trades_on_spike_days": round(avg_trades_on_spike, 2),
        }

        formula_note = (
            f"Across {len(entries_by_day)} trading days, your median activity was "
            f"{median_daily:.1f} trades per day. On {len(spike_days)} spike days, "
            f"activity exceeded {SPIKE_MULTIPLE:.1f}x your median (averaging "
            f"{metrics['avg_trades_on_spike_days']:.1f} trades/day). Keeping the first "
            f"{keep_n} trades as your standard session, the remaining {len(excess_entries)} "
            f"excess trades resulted in a net loss of ₹{estimated_cost_inr:,.2f} "
            f"(win rate: {metrics['excess_win_rate'] * 100:.0f}%)."
        )

        flagged_trade_ids = sorted(t.trade_id for t in flagged_slices)

        return HabitResult(
            key="overtrading",
            name="Taking far more trades than usual on some days",
            flagged_trade_ids=flagged_trade_ids,
            estimated_cost_inr=round(estimated_cost_inr, 2),
            confidence=confidence,
            metrics=metrics,
            formula_note=formula_note,
        )
