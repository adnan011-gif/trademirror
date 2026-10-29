"""Holding Losers habit detector.

Responsibility:
Detect patterns where losing trades are held significantly longer than winning trades.
Formula:
Compares median/mean hold duration of losing trades against winning trades. Flags losers
whose hold duration exceeds winning baseline, estimating excess holding cost or losses accrued.
"""

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade


class HoldingLosersDetector(BaseDetector):
    """Detects when losing trades are held longer than winning trades."""

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for holding losers habit."""
        return None
