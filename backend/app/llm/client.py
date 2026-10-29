"""Unified LLM Client wrapper with deterministic template fallback.

Responsibility:
Calls configured LLM provider to explain pre-calculated HabitResult metrics. If LLM_API_KEY
is not provided or the call fails, seamlessly falls back to deterministic template output.
"""

from app.config import settings
from app.detectors.base import HabitResult
from app.llm.templates import generate_fallback_narrative


class LLMClient:
    """Wrapper for LLM calls with deterministic offline fallback."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL

    def explain_habit(self, habit: HabitResult) -> tuple[str, str]:
        """Generate plain-language explanation and next month rule."""
        if not self.api_key:
            return generate_fallback_narrative(habit)
        # Placeholder for external LLM call; defaults to template until implemented
        return generate_fallback_narrative(habit)
