"""Ranking module for selecting the top high-impact habits with greedy overlap attribution.

Responsibility:
Filters candidate habit detections against minimum confidence and rupee cost thresholds,
ranks them by estimated cost, applies greedy overlap attribution to deduplicate costs across
habits sharing flagged trade IDs, and returns the top 2-3 most damaging habits with context.

Overlap attribution method:
Uses a proportional-by-count approximation (attributed_cost_inr = estimated_cost_inr *
(1 - overlap_share)), not an exact per-trade attribution. Flagged trade IDs claimed by
higher-ranked habits reduce the attributed cost of subsequent overlapping habits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.detectors.base import HabitResult
from app.models import Trade

# Named ranking constants
MIN_CONFIDENCE: float = 0.25
MIN_COST_INR: float = 500.0
MAX_HABITS: int = 3


@dataclass(frozen=True)
class RankedHabit:
    """Represents a ranked habit with attributed cost after greedy deduplication."""

    key: str
    name: str
    flagged_trade_ids: list[str]
    estimated_cost_inr: float
    confidence: float
    metrics: dict[str, Any]
    formula_note: str
    attributed_cost_inr: float
    overlap_share: float


@dataclass(frozen=True)
class RankedResult:
    """Result of habit ranking and portfolio-level behavioral synthesis."""

    habits: list[RankedHabit]
    total_attributed_cost_inr: float
    overlaps: list[dict[str, Any]]
    dropped: list[dict[str, Any]]
    material: bool
    reason: str | None
    context: dict[str, Any] = field(default_factory=dict)


def rank_habits(results: list[HabitResult], trades: list[Trade]) -> RankedResult:
    """Filter, rank, and attribute costs for detected behavioral habits.

    Args:
        results: Candidate HabitResult objects from active detectors.
        trades: Full list of paired round-trip trades for contextual summary metrics.

    Returns:
        RankedResult containing top attributed habits (up to MAX_HABITS), overlap
        breakdown, dropped habit audit, materiality flag, and summary context.
    """
    # Summary context from trades
    n_trades = len(trades)
    gross_pnl_inr = round(sum(t.gross_pnl for t in trades), 2)
    gross_loss_inr = round(sum(abs(t.gross_pnl) for t in trades if t.gross_pnl < 0), 2)
    winners = sum(1 for t in trades if t.gross_pnl > 0)
    win_rate = round(winners / n_trades, 4) if n_trades > 0 else 0.0

    context = {
        "n_trades": n_trades,
        "gross_pnl_inr": gross_pnl_inr,
        "gross_loss_inr": gross_loss_inr,
        "win_rate": win_rate,
    }

    # Step 1: Drop results with confidence < MIN_CONFIDENCE or estimated_cost_inr < MIN_COST_INR
    qualified: list[HabitResult] = []
    dropped: list[dict[str, Any]] = []

    for r in results:
        reasons = []
        if r.confidence < MIN_CONFIDENCE:
            reasons.append(f"confidence {r.confidence:.2f} < {MIN_CONFIDENCE:.2f}")
        if r.estimated_cost_inr < MIN_COST_INR:
            reasons.append(f"estimated cost ₹{r.estimated_cost_inr:,.2f} < ₹{MIN_COST_INR:,.2f}")

        if reasons:
            dropped.append({
                "key": r.key,
                "name": r.name,
                "reason": "; ".join(reasons),
                "confidence": r.confidence,
                "estimated_cost_inr": r.estimated_cost_inr,
            })
        else:
            qualified.append(r)

    # Step 2: Sort by estimated_cost_inr descending; ties broken by key alphabetically
    qualified.sort(key=lambda h: (-h.estimated_cost_inr, h.key))

    # Step 3: Overlap handling (greedy, in sorted order)
    # Proportional-by-count approximation:
    # overlap_share = (flagged trade ids already claimed by higher-ranked habits)
    #                 / (its flagged trade ids)
    # attributed_cost_inr = estimated_cost_inr * (1 - overlap_share), rounded to 2.
    claimed_ids: set[str] = set()
    overlaps: list[dict[str, Any]] = []
    candidates: list[RankedHabit] = []
    processed_habits: list[HabitResult] = []

    for habit in qualified:
        flagged_set = set(habit.flagged_trade_ids)
        already_claimed = flagged_set & claimed_ids
        overlap_share = len(already_claimed) / len(flagged_set) if flagged_set else 0.0
        attributed_cost = round(habit.estimated_cost_inr * (1.0 - overlap_share), 2)

        # Record pairwise overlaps with higher-ranked habits
        for prev in processed_habits:
            shared = sorted(set(prev.flagged_trade_ids) & flagged_set)
            if shared:
                overlaps.append({
                    "habits": [prev.key, habit.key],
                    "shared_trade_ids": shared,
                })

        claimed_ids.update(flagged_set)
        processed_habits.append(habit)

        candidates.append(
            RankedHabit(
                key=habit.key,
                name=habit.name,
                flagged_trade_ids=habit.flagged_trade_ids,
                estimated_cost_inr=habit.estimated_cost_inr,
                confidence=habit.confidence,
                metrics=habit.metrics,
                formula_note=habit.formula_note,
                attributed_cost_inr=attributed_cost,
                overlap_share=round(overlap_share, 4),
            )
        )

    # Step 4: Re-sort by attributed_cost_inr descending (same tie-break), keep top MAX_HABITS
    candidates.sort(key=lambda h: (-h.attributed_cost_inr, h.key))
    kept_habits = candidates[:MAX_HABITS]

    total_attributed_cost = round(sum(h.attributed_cost_inr for h in kept_habits), 2)
    material = len(kept_habits) > 0
    reason = None if material else "No habit cleared the evidence bar this month"

    return RankedResult(
        habits=kept_habits,
        total_attributed_cost_inr=total_attributed_cost,
        overlaps=overlaps,
        dropped=dropped,
        material=material,
        reason=reason,
        context=context,
    )
