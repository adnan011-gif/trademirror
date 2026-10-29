"""Habit detection modules and registry for TradeMirror."""

from app.detectors.averaging_down import AveragingDownDetector
from app.detectors.base import BaseDetector, HabitResult
from app.detectors.holding_losers import HoldingLosersDetector
from app.detectors.oversizing import OversizingDetector
from app.detectors.overtrading import OvertradingDetector
from app.detectors.revenge_trading import RevengeTradingDetector

# Fixed registry order of detector instances
ALL_DETECTORS: list[BaseDetector] = [
    HoldingLosersDetector(),
    RevengeTradingDetector(),
    OvertradingDetector(),
    OversizingDetector(),
    AveragingDownDetector(),
]

__all__ = [
    "ALL_DETECTORS",
    "AveragingDownDetector",
    "BaseDetector",
    "HabitResult",
    "HoldingLosersDetector",
    "OversizingDetector",
    "OvertradingDetector",
    "RevengeTradingDetector",
]
