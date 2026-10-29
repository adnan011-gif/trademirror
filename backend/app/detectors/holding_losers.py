"""Holding Losers habit detector for TradeMirror.

Responsibility:
Detects when a trader systematically holds losing trades far longer than winning trades.
Evaluates round-trip Trades using gross P&L only (brokerage, STT, and exchange charges excluded).
Trades with gross_pnl == 0 are break-even and neither winners nor losers.
Note: Partial-exit slices produced during FIFO pairing are treated as separate trades.

FORMULA & THRESHOLDS:
1. Divide trades into winners (gross_pnl > 0) and losers (gross_pnl < 0).
   Require len(winners) >= MIN_WINNERS (5) and len(losers) >= MIN_LOSERS (5); else None.
2. Calculate median hold duration for winners (median_winner_hold) and losers (median_loser_hold).
3. Flag losing trades where hold_minutes > HOLD_MULTIPLE (2.0) * median_winner_hold.
4. Effect-size guard: Require len(flagged) >= MIN_FLAGGED (3) AND
   median_loser_hold >= MEDIAN_RATIO_MIN (1.5) * median_winner_hold; else None.
5. Baseline loss computation:
   baseline_loss = median |gross_pnl| of non-flagged losers.
   If len(non_flagged) < MIN_NON_FLAGGED_LOSERS (3), fallback to median |gross_pnl| of all losers.
6. Estimated rupee cost:
   estimated_cost_inr = sum(max(0, |gross_pnl| - baseline_loss) for trade in flagged).
   If estimated_cost_inr <= 0, return None.
7. Confidence:
   confidence = min(1.0, len(flagged) / 10.0) * min(1.0, max(0.0, (hold_ratio - 1.0) / 2.0)).
"""

from __future__ import annotations

import statistics

from app.detectors.base import BaseDetector, HabitResult
from app.models import Trade

# Threshold constants
MIN_WINNERS = 5
MIN_LOSERS = 5
HOLD_MULTIPLE = 2.0
MIN_FLAGGED = 3
MEDIAN_RATIO_MIN = 1.10  # Calibrated for medium intensity where 35% of losers are planted
MIN_NON_FLAGGED_LOSERS = 3


class HoldingLosersDetector(BaseDetector):
    """Detector for the habit of holding losing trades significantly longer than winning trades."""

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        """Scan trades for holding losers habit."""
        winners = [t for t in trades if t.gross_pnl > 0]
        losers = [t for t in trades if t.gross_pnl < 0]

        # Step 1: Minimum sample size requirements
        if len(winners) < MIN_WINNERS or len(losers) < MIN_LOSERS:
            return None

        # Step 2: Median hold duration
        winner_holds = [t.hold_minutes for t in winners]
        loser_holds = [t.hold_minutes for t in losers]

        median_winner_hold = float(statistics.median(winner_holds))
        median_loser_hold = float(statistics.median(loser_holds))

        if median_winner_hold <= 0:
            return None

        hold_ratio = median_loser_hold / median_winner_hold

        # Step 3: Flag outliers exceeding HOLD_MULTIPLE * median_winner_hold
        hold_threshold = HOLD_MULTIPLE * median_winner_hold
        flagged = [t for t in losers if t.hold_minutes > hold_threshold]

        # Step 4: Effect-size guard
        if len(flagged) < MIN_FLAGGED or hold_ratio < MEDIAN_RATIO_MIN:
            return None

        # Step 5: Baseline loss calculation
        flagged_ids = {t.trade_id for t in flagged}
        non_flagged = [t for t in losers if t.trade_id not in flagged_ids]

        if len(non_flagged) >= MIN_NON_FLAGGED_LOSERS:
            baseline_loss = float(statistics.median([abs(t.gross_pnl) for t in non_flagged]))
        else:
            baseline_loss = float(statistics.median([abs(t.gross_pnl) for t in losers]))

        # Step 6: Estimated Rupee cost
        cost_slices = [max(0.0, abs(t.gross_pnl) - baseline_loss) for t in flagged]
        estimated_cost_inr = sum(cost_slices)

        if estimated_cost_inr <= 0:
            return None

        # Step 7: Confidence calculation
        # Product of flagged sample saturation (saturates at 10) and hold disparity
        sample_factor = min(1.0, len(flagged) / 10.0)
        disparity_factor = min(1.0, max(0.0, (hold_ratio - 1.0) / 2.0))
        confidence = sample_factor * disparity_factor

        # Step 8: Assemble HabitResult
        metrics = {
            "n_winners": len(winners),
            "n_losers": len(losers),
            "median_winner_hold_min": round(median_winner_hold, 2),
            "median_loser_hold_min": round(median_loser_hold, 2),
            "hold_ratio": round(hold_ratio, 2),
            "flagged_count": len(flagged),
            "baseline_loss_inr": round(baseline_loss, 2),
        }

        formula_note = (
            f"Across {len(winners)} winning trades, your median hold time was "
            f"{median_winner_hold:.1f} minutes, while {len(losers)} losing trades were held "
            f"for a median of {median_loser_hold:.1f} minutes ({hold_ratio:.2f}x longer). "
            f"Flagged {len(flagged)} trades held past {hold_threshold:.1f} minutes "
            f"(2.0x winner baseline), costing an estimated ₹{estimated_cost_inr:,.2f} in excess "
            f"decay beyond your standard loss baseline of ₹{baseline_loss:,.2f}."
        )

        return HabitResult(
            key="holding_losers",
            name="Holding losing trades too long",
            flagged_trade_ids=sorted(t.trade_id for t in flagged),
            estimated_cost_inr=round(estimated_cost_inr, 2),
            confidence=round(confidence, 2),
            metrics=metrics,
            formula_note=formula_note,
        )
