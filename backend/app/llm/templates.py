"""Prompt and fallback templates for narrative generation.

Responsibility:
Provides prompt templates instructing the LLM to explain deterministic habit metrics,
as well as deterministic string template fallbacks used when no API key is configured.
"""

from app.detectors.base import HabitResult


def generate_fallback_narrative(habit: HabitResult) -> tuple[str, str]:
    """Generate deterministic explanation and next month rule when LLM is unavailable."""
    explanation = (
        f"Detected {habit.name} with an estimated cost of ₹{habit.estimated_cost_inr:,.2f} "
        f"across {len(habit.flagged_trade_ids)} flagged trades."
    )
    rule = "Follow a strict pre-defined trade limit and stop-loss parameter."
    return explanation, rule
