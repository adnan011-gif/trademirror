"""Deterministic fallback templates and approved behavioral rules.

Responsibility:
Provides fixed approved rules per habit key, deterministic string templates
filling in computed metrics and attributed cost when LLM is unavailable or ungrounded,
and standard summary sentences. Templates describe behaviour only without financial
advice or market predictions.
"""

from __future__ import annotations

from typing import Any

from app.ranking import RankedHabit, RankedResult

# Fixed approved rules per habit. Any numbers in them are their own fixed constants.
APPROVED_RULES: dict[str, str] = {
    "holding_losers": (
        "Set a hard time stop to exit any losing trade if it has not recovered within "
        "30 minutes of entry."
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
        "Limit position sizing to a maximum of 2 lots per order regardless of preceding "
        "win or loss streaks."
    ),
    "averaging_down": (
        "Never add contracts to an existing position that is currently trading below "
        "its average entry price."
    ),
}

NOTHING_MATERIAL_SUMMARY = "No behavioral habit cleared the evidence bar this month."


def get_approved_rule(habit_key: str) -> str:
    """Return the approved behavioral rule for a given habit key."""
    if habit_key not in APPROVED_RULES:
        raise KeyError(f"Unknown habit key: {habit_key}")
    return APPROVED_RULES[habit_key]


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
            f"{fl_cnt} losing positions cost an attributed ₹{cost:,.2f} in excess decay."
        )

    if key == "revenge_trading":
        gap_avg = m.get("avg_gap_minutes", 0.0)
        fl_entries = m.get("flagged_entries", len(habit.flagged_trade_ids))
        return (
            f"You re-entered the market within an average of {gap_avg:.1f} minutes following "
            f"losses, escalating size across {fl_entries} entries. This rush to recover losses "
            f"resulted in an attributed cost of ₹{cost:,.2f}."
        )

    if key == "overtrading":
        sp_cnt = m.get("spike_day_count", len(m.get("spike_days", [])))
        sp_avg = m.get("avg_trades_on_spike_days", 0.0)
        base_med = m.get("median_daily_trades", 0.0)
        excess = m.get("excess_trades", 0)
        return (
            f"You traded during volume spikes across {sp_cnt} days, averaging {sp_avg:.1f} "
            f"trades compared to your baseline of {base_med:.1f}. These {excess} excess trades "
            f"produced an attributed cost of ₹{cost:,.2f}."
        )

    if key == "oversizing":
        base_lots = m.get("median_lots", 0.0)
        fl_entries = m.get("flagged_entries", 0)
        return (
            f"You increased position sizes beyond your typical baseline of {base_lots:.1f} "
            f"lots following streaks across {fl_entries} entries. These oversized positions "
            f"led to an attributed cost of ₹{cost:,.2f}."
        )

    if key == "averaging_down":
        fl_entries = m.get("flagged_entries", 0)
        return (
            f"You added contracts to underwater positions across {fl_entries} entry events as "
            f"prices moved against you. These losing add-on trades resulted in an attributed "
            f"cost of ₹{cost:,.2f}."
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
        summary = (
            f"Your trading this month was impacted by {ranked.habits[0].name} "
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
                "rule": get_approved_rule(h.key),
            }
        )

    return {
        "summary": summary,
        "habits": habits_list,
    }
