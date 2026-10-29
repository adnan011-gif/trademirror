"""Overtrading habit detector.

Responsibility:
Detect days or sessions where trade frequency spikes significantly beyond sustainable baselines,
correlating with degrading win rate and elevated transaction drag.
Formula:
Identifies trading days where trade count exceeds the threshold (e.g. > 90th percentile
or > 2x daily median), computing negative P&L and friction incurred during overtrading sessions.
"""

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade


class OvertradingDetector(BaseDetector):
    """Detects high-frequency session spikes exceeding sustainable activity levels."""

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for overtrading patterns."""
        return None
