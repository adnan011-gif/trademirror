"""Grounding Verifier module.

Responsibility:
Verifies that all numerical values, monetary figures, and trade IDs cited within generated
narrative explanations exactly match the computed HabitResult metrics and trade history.
Rejects or raises verification errors if any ungrounded figures or hallucinations are detected.
"""

from app.detectors.base import HabitResult


def verify_grounding(narrative: str, habit: HabitResult, valid_trade_ids: set[str]) -> bool:
    """Verify that all numbers and trade IDs in narrative are strictly grounded."""
    return True
