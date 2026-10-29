"""End-to-end post-trade behavioural analysis pipeline for TradeMirror.

Responsibility:
Coordinates order parsing, FIFO round-trip matching, execution of all registered
habit detectors, resilient error capture, and high-impact habit ranking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from app.detectors import ALL_DETECTORS
from app.detectors.base import HabitResult
from app.models import OpenPosition, Order, Trade
from app.pairing import pair_orders
from app.parsers.orders_csv import IngestWarning, parse_orders
from app.ranking import RankedResult, rank_habits

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Consolidated result of the TradeMirror analysis pipeline."""

    ranked: RankedResult
    raw_results: list[HabitResult | None]
    ingest_warnings: list[IngestWarning]
    ingest_counts: dict[str, int]
    pairing_anomalies: list[str]
    detector_errors: list[dict[str, Any]]
    trades: list[Trade] = field(default_factory=list)
    open_positions: list[OpenPosition] = field(default_factory=list)

    @property
    def warnings(self) -> list[IngestWarning]:
        """Convenience alias for ingest_warnings."""
        return self.ingest_warnings

    @property
    def counts(self) -> dict[str, int]:
        """Convenience alias for ingest_counts."""
        return self.ingest_counts

    @property
    def anomalies(self) -> list[str]:
        """Convenience alias for pairing_anomalies."""
        return self.pairing_anomalies


def run_pipeline(
    source: str | Path | bytes | IO[bytes] | IO[str] | list[Order],
) -> PipelineResult:
    """Run the complete post-trade analysis pipeline.

    Flow:
    1. Parse and validate canonical orders CSV (or accept pre-parsed Order list).
       IngestError propagates unchanged on fatal parse/schema failure.
    2. Match orders into round-trip trades using FIFO pairing.
    3. Run every detector in ALL_DETECTORS. A detector raising an exception does
       NOT crash the pipeline; it is caught, logged, and recorded in detector_errors.
    4. Rank detected habits with greedy overlap attribution and contextual metrics.

    Args:
        source: CSV file path, string content, byte stream, or pre-parsed Order list.

    Returns:
        PipelineResult containing ranked habits, raw outputs, pairing anomalies,
        ingest warnings, counts, and detector error diagnostics.
    """
    if isinstance(source, list):
        orders: list[Order] = source
        warnings: list[IngestWarning] = []
        counts: dict[str, int] = {
            "total_rows": len(source),
            "valid_orders": len(source),
        }
    else:
        # IngestError propagates unchanged
        ingest = parse_orders(source)
        orders = ingest.orders
        warnings = ingest.warnings
        counts = ingest.counts

    # 2. FIFO order pairing
    pairing = pair_orders(orders)

    # 3. Run all registered detectors with exception isolation
    raw_results: list[HabitResult | None] = []
    detector_errors: list[dict[str, Any]] = []

    for detector in ALL_DETECTORS:
        det_name = getattr(detector, "key", detector.__class__.__name__)
        try:
            res = detector.detect(pairing.trades)
            raw_results.append(res)
        except Exception as exc:
            logger.exception("Detector '%s' failed unexpectedly: %s", det_name, exc)
            detector_errors.append({
                "detector": det_name,
                "error": str(exc),
            })
            raw_results.append(None)

    # 4. Rank habits
    active_results = [r for r in raw_results if r is not None]
    ranked = rank_habits(active_results, pairing.trades)

    return PipelineResult(
        ranked=ranked,
        raw_results=raw_results,
        ingest_warnings=warnings,
        ingest_counts=counts,
        pairing_anomalies=pairing.anomalies,
        detector_errors=detector_errors,
        trades=pairing.trades,
        open_positions=pairing.open_positions,
    )
