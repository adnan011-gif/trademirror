"""Base interface and return types for behavioural habit detectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models import Trade


@dataclass(frozen=True)
class HabitResult:
    """Deterministic result emitted by a habit detector."""

    key: str
    name: str
    flagged_trade_ids: list[str]
    estimated_cost_inr: float
    confidence: float
    metrics: dict[str, Any] = field(default_factory=dict)
    formula_note: str = ""


class BaseDetector(ABC):
    """Abstract base class for all habit detection algorithms."""

    @abstractmethod
    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Analyze a sequence of closed round-trip trades and return a habit result if detected."""
        raise NotImplementedError
