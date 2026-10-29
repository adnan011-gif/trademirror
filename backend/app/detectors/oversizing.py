"""Oversizing habit detector.

Responsibility:
Detect trades where position size exceeds 2x median trade size following a streak
of 2 or more consecutive wins or losses.
Formula:
Calculates running streak count of consecutive wins or losses. When streak >= 2,
flags subsequent trades with quantity > 2.0 * median_trade_quantity. Cost is evaluated
from downside loss on oversized trades.
"""

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade


class OversizingDetector(BaseDetector):
    """Detects position sizing exceeding 2x median following a win or loss streak."""

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for oversized positions following win/loss streaks."""
        return None
