"""Averaging Down habit detector.

Responsibility:
Detect behavior where orders add to an already losing open position rather than cutting losses.
Formula:
Identifies trades where multiple sequential buy (or sell-short) orders occur at
worsening entry prices while unrealized P&L is negative before eventual closure.
"""

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade


class AveragingDownDetector(BaseDetector):
    """Detects adding capital to losing open positions."""

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for averaging down patterns."""
        return None
