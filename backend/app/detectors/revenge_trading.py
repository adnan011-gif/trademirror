"""Revenge Trading habit detector.

Responsibility:
Detect re-entry within 15 minutes of a losing trade close with position size >= 1.5x of
the previous trade.
Formula:
Identifies trades where (entry_time - previous_loss_exit_time) <= 15 minutes and
quantity >= 1.5 * previous_loss_quantity. Rupee cost is the net loss incurred on revenge trades.
"""

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade


class RevengeTradingDetector(BaseDetector):
    """Detects rapid re-entry with increased size following a loss."""

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for revenge trading patterns."""
        return None
