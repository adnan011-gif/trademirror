"""Ranking module for selecting the top 2-3 high-impact habits.

Responsibility:
Sorts candidate habit results strictly by estimated rupee cost descending, applies deduplication,
and returns the top 2-3 habits that cost the trader the most money.
"""

from app.detectors.base import HabitResult


def rank_habits(results: list[HabitResult], max_habits: int = 3) -> list[HabitResult]:
    """Rank detected habits descending by estimated rupee cost and return top 2-3."""
    return sorted(results, key=lambda h: h.estimated_cost_inr, reverse=True)[:max_habits]
