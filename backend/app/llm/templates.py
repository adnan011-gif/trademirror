"""Deterministic fallback templates and approved behavioral rules.

Responsibility:
Provides approved rules per habit key (derived from trader data where applicable,
or fixed rules of thumb with documented rationales), deterministic string templates
filling in computed metrics and attributed cost, and standard summary sentences.
Templates describe behaviour only without financial advice or market predictions.
"""

from __future__ import annotations

import math
from typing import Any

from app.ranking import RankedHabit, RankedResult

# Base fallback templates for approved rules
APPROVED_RULES: dict[str, str] = {
    "holding_losers": (
        "Exit any losing trade that has not recovered within 20 minutes of entry, "
        "which is about how long your winning trades last."
    ),
    "revenge_trading": (
        "Enforce a mandatory 30-minute cooldown period following any losing trade before "
        "entering a new position."
    ),
    "overtrading": (
        "Cap daily activity at a maximum of 6 completed trades and stop trading for the "
        "day once reached."
    ),
    "oversizing": (
        "After two wins or two losses in a row, keep your position at your usual "
        "1 lot instead of increasing it."
    ),
    "averaging_down": (
        "Never add contracts to an existing position that is currently trading below "
        "its average entry price."
    ),
}

# Short lowercase noun phrases for natural reading in single-habit summaries
HABIT_LABELS: dict[str, str] = {
    "holding_losers": "holding losing trades too long",
    "revenge_trading": "re-entering fast after a loss with a bigger size",
    "overtrading": "taking far more trades than usual on some days",
    "oversizing": "taking an oversized position after a win or loss streak",
    "averaging_down": "adding to a losing position",
}

NOTHING_MATERIAL_SUMMARY = "No behavioral habit cleared the evidence bar this month."


def get_approved_rule(habit_key: str, metrics: dict[str, Any] | None = None) -> str:
    """Return the approved behavioral rule for a given habit key.

    Derived dynamically from the trader's own data where applicable:
    - holding_losers: time stop equals median winner hold, rounded to nearest 5m (min 5).
    - overtrading: daily cap equals ceil(median_daily_trades) + 1.
    - oversizing: typical size equals max(1, round(median_lots)).

    Fixed constants used only for behavioral rules of thumb:
    - revenge_trading: 30 minutes emotional cooldown.
    - averaging_down: zero add-ons to losers.
    """
    m = metrics or {}

    if habit_key == "holding_losers":
        w_med = m.get("median_winner_hold_min", 20.0)
        time_stop = max(5, int(round(w_med / 5.0) * 5))
        return (
            f"Exit any losing trade that has not recovered within {time_stop} minutes of entry, "
            f"which is about how long your winning trades last."
        )

    if habit_key == "overtrading":
        base_med = m.get("median_daily_trades", 5.0)
        cap = int(math.ceil(base_med)) + 1
        return (
            f"Cap daily activity at a maximum of {cap} completed trades and stop trading "
            f"for the day once reached."
        )

    if habit_key == "revenge_trading":
        # Fixed constant: 30-minute cooldown is a behavioral rule of thumb for emotional resetting,
        # not a specific statistical property of the trader.
        return (
            "Enforce a mandatory 30-minute cooldown period following any losing trade before "
            "entering a new position."
        )

    if habit_key == "oversizing":
        # Derived from the trader's data: normal position size from median_lots
        med_lots = m.get("median_lots", 1.0)
        n_lots = max(1, int(round(med_lots)))
        lot_word = "lot" if n_lots == 1 else "lots"
        return (
            f"After two wins or two losses in a row, keep your position at your usual "
            f"{n_lots} {lot_word} instead of increasing it."
        )

    if habit_key == "averaging_down":
        # Contains no numbers: strict behavioral prohibition against adding to losing positions.
        return (
            "Never add contracts to an existing position that is currently trading below "
            "its average entry price."
        )

    if habit_key in APPROVED_RULES:
        return APPROVED_RULES[habit_key]

    raise KeyError(f"Unknown habit key: {habit_key}")


def generate_template_explanation(habit: RankedHabit) -> str:
    """Generate a deterministic 2-sentence explanation for a single ranked habit."""
    key = habit.key
    m = habit.metrics
    cost = habit.attributed_cost_inr

    if key == "holding_losers":
        w_med = m.get("median_winner_hold_min", 0.0)
        fl_med = m.get("flagged_median_hold_min", 0.0)
        fl_cnt = m.get("flagged_count", len(habit.flagged_trade_ids))
        return (
            f"Across winning trades your median hold was {w_med:.1f} minutes, but flagged "
            f"losing trades were held for a median of {fl_med:.1f} minutes. Holding these "
            f"{fl_cnt} losing positions cost an attributed ₹{cost:,.2f} in extra loss beyond "
            f"what you normally lose on a losing trade."
        )

    if key == "revenge_trading":
        gap_avg = m.get("avg_gap_minutes", 0.0)
        fl_entries = m.get("flagged_entries", len(habit.flagged_trade_ids))
        return (
            f"You re-entered the market within an average of {gap_avg:.1f} minutes following "
            f"losses, escalating size across {fl_entries} entries. This rush to recover losses "
            f"resulted in an attributed cost of ₹{cost:,.2f} in net loss on these re-entries."
        )

    if key == "overtrading":
        sp_cnt = m.get("spike_day_count", len(m.get("spike_days", [])))
        sp_avg = m.get("avg_trades_on_spike_days", 0.0)
        base_med = m.get("median_daily_trades", 0.0)
        excess = m.get("excess_trades", 0)
        return (
            f"You traded during volume spikes across {sp_cnt} days, averaging {sp_avg:.1f} "
            f"trades compared to your baseline of {base_med:.1f}. These {excess} excess trades "
            f"produced an attributed cost of ₹{cost:,.2f} in net loss on the extra trades."
        )

    if key == "oversizing":
        base_lots = m.get("median_lots", 0.0)
        fl_entries = m.get("flagged_entries", 0)
        return (
            f"You increased position sizes beyond your typical baseline of {base_lots:.1f} "
            f"lots following streaks across {fl_entries} entries. These oversized positions "
            f"led to an attributed cost of ₹{cost:,.2f} in extra loss attributable to the "
            f"larger size."
        )

    if key == "averaging_down":
        fl_entries = m.get("flagged_entries", 0)
        return (
            f"You added contracts to underwater positions across {fl_entries} entry events as "
            f"prices moved against you. These losing add-on trades resulted in an attributed "
            f"cost of ₹{cost:,.2f} in net loss on the added positions."
        )

    return (
        f"Detected {habit.name} with an attributed cost of ₹{cost:,.2f} across "
        f"{len(habit.flagged_trade_ids)} flagged trades."
    )


def generate_template_narrative(ranked: RankedResult) -> dict[str, Any]:
    """Generate the full deterministic template narrative from a RankedResult."""
    if not ranked.material or not ranked.habits:
        return {
            "summary": NOTHING_MATERIAL_SUMMARY,
            "habits": [],
        }

    n_habits = len(ranked.habits)
    total_cost = ranked.total_attributed_cost_inr

    if n_habits == 1:
        h0 = ranked.habits[0]
        label = HABIT_LABELS.get(
            h0.key,
            h0.name[0].lower() + h0.name[1:] if h0.name else h0.key,
        )
        summary = (
            f"1 habit stood out this month: {label}, "
            f"with an attributed cost of ₹{total_cost:,.2f}."
        )
    else:
        summary = (
            f"Your trading this month was impacted by {n_habits} behavioral habits "
            f"with a combined attributed cost of ₹{total_cost:,.2f}."
        )

    habits_list: list[dict[str, str]] = []
    for h in ranked.habits:
        habits_list.append(
            {
                "key": h.key,
                "explanation": generate_template_explanation(h),
                "rule": get_approved_rule(h.key, h.metrics),
            }
        )

    return {
        "summary": summary,
        "habits": habits_list,
    }
