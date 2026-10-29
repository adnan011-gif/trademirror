"""API route definitions for TradeMirror."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from app.api.schemas import (
    AnalysisResponse,
    ContextInfo,
    DatasetInfo,
    EvidenceTrade,
    HabitResponseItem,
    HealthResponse,
    NarrativeInfo,
    SampleItemResponse,
    VerificationInfo,
    WarningItem,
)
from app.config import settings
from app.llm.templates import get_approved_rule
from app.narrative import generate_narrative
from app.parsers.orders_csv import IngestError
from app.pipeline import PipelineResult, run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()

# Fixed whitelist of sample datasets
SAMPLE_CATALOGUE: list[dict[str, str]] = [
    {
        "name": "clean",
        "label": "A clean month: no problem habits",
        "description": (
            "Disciplined trading with no material behavioral habits "
            "clearing the detection threshold."
        ),
    },
    {
        "name": "mixed",
        "label": "Mixed habits: multiple overlapping patterns",
        "description": (
            "A realistic month exhibiting holding losers, revenge trading, and overtrading."
        ),
    },
    {
        "name": "messy",
        "label": "Messy order book: cancelled and rejected orders",
        "description": (
            "Realistic broker export containing duplicate rows, partial fills, "
            "cancellations, and rejections."
        ),
    },
    {
        "name": "single_holding_losers",
        "label": "Holding losing trades too long",
        "description": (
            "Losing trades held significantly longer than winners, producing "
            "attributed decay and excess loss."
        ),
    },
    {
        "name": "single_revenge_trading",
        "label": "Revenge trading after losses",
        "description": (
            "Rapid, oversized re-entries following losing trades within minutes of closing."
        ),
    },
    {
        "name": "single_overtrading",
        "label": "Overtrading on high-activity days",
        "description": (
            "Abnormal volume spikes and trade count clusters far exceeding "
            "typical daily baselines."
        ),
    },
    {
        "name": "single_oversizing",
        "label": "Oversizing on win/loss streaks",
        "description": (
            "Position sizes aggressively scaled up after consecutive winning or losing runs."
        ),
    },
    {
        "name": "single_averaging_down",
        "label": "Averaging down into losing positions",
        "description": (
            "Adding contracts to already losing trades hoping to lower entry price."
        ),
    },
]


SAMPLE_FILES: dict[str, str] = {
    "clean": "clean.csv",
    "mixed": "mixed.csv",
    "messy": "messy.csv",
    "single_holding_losers": "single_holding_losers.csv",
    "single_revenge_trading": "single_revenge_trading.csv",
    "single_overtrading": "single_overtrading.csv",
    "single_oversizing": "single_oversizing.csv",
    "single_averaging_down": "single_averaging_down.csv",
}

# In-memory per-IP rate limiter. Limitation: per-process, resets on restart.
_rate_limit_lock = threading.Lock()
_ip_request_history: dict[str, list[float]] = {}


def reset_rate_limiter() -> None:
    """Clear in-memory rate limit records for testing."""
    with _rate_limit_lock:
        _ip_request_history.clear()


def check_rate_limit(request: Request) -> Response | None:
    """Check in-memory per-IP rate limit for protected endpoints.

    Limitation: per-process, resets on restart.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    now = time.time()
    window = 60.0
    limit = settings.RATE_LIMIT_PER_MINUTE

    with _rate_limit_lock:
        timestamps = _ip_request_history.get(client_ip, [])
        valid_timestamps = [t for t in timestamps if now - t < window]
        if len(valid_timestamps) >= limit:
            oldest = valid_timestamps[0]
            retry_after = max(1, int(window - (now - oldest)))
            request_id = getattr(request.state, "request_id", "")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please try again later.",
                    "request_id": request_id,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-Request-ID": request_id,
                },
            )
        valid_timestamps.append(now)
        _ip_request_history[client_ip] = valid_timestamps

    return None


def sanitize_text(text: str) -> str:
    """Sanitize text to guarantee forbidden strings and paths are excluded."""
    for forbidden in ("ground_truth", "data/", "Traceback"):
        if forbidden in text:
            text = text.replace(forbidden, "[redacted]")
    return text


def build_analysis_response(
    source_name: str,
    pipeline_result: PipelineResult,
) -> AnalysisResponse:
    """Construct a grounded, schema-validated AnalysisResponse."""
    narrative_result = generate_narrative(
        pipeline_result.ranked,
        pipeline_result.trades,
        settings,
    )

    trades_by_id = {t.trade_id: t for t in pipeline_result.trades}
    narrative_habits = {
        h["key"]: h for h in narrative_result.narrative.get("habits", [])
    }

    habits_list: list[HabitResponseItem] = []
    for rank, h in enumerate(pipeline_result.ranked.habits, start=1):
        narr_h = narrative_habits.get(h.key, {})
        explanation = narr_h.get("explanation", "")
        rule = narr_h.get("rule", get_approved_rule(h.key, h.metrics))

        # Evidence trades: sorted by gross_pnl ascending (largest loss first), capped at 25
        flagged_trades = [
            trades_by_id[tid] for tid in h.flagged_trade_ids if tid in trades_by_id
        ]
        flagged_trades.sort(key=lambda t: t.gross_pnl)
        capped_trades = flagged_trades[:25]

        evidence_trades = [
            EvidenceTrade(
                trade_id=t.trade_id,
                trading_date=str(t.trading_date),
                entry_time=t.entry_time.isoformat(),
                exit_time=t.exit_time.isoformat(),
                symbol=t.symbol,
                instrument_type=t.instrument_type,
                strike=t.strike,
                direction=t.direction,
                quantity=t.quantity,
                lots=round(t.trade_lots, 4),
                hold_minutes=round(t.hold_minutes, 2),
                gross_pnl=round(t.gross_pnl, 2),
            )
            for t in capped_trades
        ]

        habits_list.append(
            HabitResponseItem(
                key=h.key,
                name=h.name,
                rank=rank,
                attributed_cost_inr=h.attributed_cost_inr,
                estimated_cost_inr=h.estimated_cost_inr,
                overlap_share=h.overlap_share,
                confidence=h.confidence,
                explanation=explanation,
                rule=rule,
                formula_note=h.formula_note,
                metrics=h.metrics,
                evidence_trades=evidence_trades,
                evidence_total=len(h.flagged_trade_ids),
                evidence_truncated=len(h.flagged_trade_ids) > 25,
            )
        )

    # Ingest warnings capped at 50
    warnings_list = [
        WarningItem(
            code=w.code,
            row_number=w.row_number,
            order_id=w.order_id,
            message=w.message,
        )
        for w in pipeline_result.ingest_warnings[:50]
    ]

    # Clean detector error strings without stack traces or paths
    detector_errors_list: list[str] = []
    for err in pipeline_result.detector_errors:
        det = err.get("detector", "unknown")
        raw_msg = str(err.get("error", "")).splitlines()[0][:100]
        cleaned_msg = sanitize_text(raw_msg)
        detector_errors_list.append(f"{det}: {cleaned_msg}")

    return AnalysisResponse(
        dataset=DatasetInfo(
            source=source_name,
            n_orders_raw=pipeline_result.ingest_counts.get("total_rows", 0),
            n_orders_kept=pipeline_result.ingest_counts.get("valid_orders", 0),
            n_trades=len(pipeline_result.trades),
            counts=pipeline_result.ingest_counts,
        ),
        context=ContextInfo(
            gross_pnl_inr=pipeline_result.ranked.context.get("gross_pnl_inr", 0.0),
            gross_loss_inr=pipeline_result.ranked.context.get("gross_loss_inr", 0.0),
            win_rate=pipeline_result.ranked.context.get("win_rate", 0.0),
            total_attributed_cost_inr=pipeline_result.ranked.total_attributed_cost_inr,
        ),
        material=pipeline_result.ranked.material,
        summary=narrative_result.narrative.get("summary", ""),
        habits=habits_list,
        overlaps=pipeline_result.ranked.overlaps,
        dropped=pipeline_result.ranked.dropped,
        warnings=warnings_list,
        warnings_total=len(pipeline_result.ingest_warnings),
        pairing_anomalies=pipeline_result.pairing_anomalies,
        narrative=NarrativeInfo(
            source=narrative_result.source,
            fallback_reason=narrative_result.fallback_reason,
            llm_attempts=narrative_result.llm_attempts,
        ),
        verification=VerificationInfo(
            passed=narrative_result.verification.passed,
            checked_numbers=narrative_result.verification.checked_numbers,
            checked_trade_ids=narrative_result.verification.checked_trade_ids,
            failures=narrative_result.verification.failures,
        ),
        detector_errors=detector_errors_list,
    )


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return API health status."""
    return HealthResponse(status="ok")


@router.get("/samples", response_model=list[SampleItemResponse])
def get_samples() -> list[SampleItemResponse]:
    """Return whitelist catalogue of built-in sample datasets."""
    return [SampleItemResponse(**item) for item in SAMPLE_CATALOGUE]


@router.get("/sample/{name:path}", response_model=AnalysisResponse)
def get_sample_analysis(name: str, request: Request) -> Any:
    """Return analysis for a built-in sample dataset.

    Executed in worker threadpool via plain def to keep the event loop responsive.
    """
    request_id = getattr(request.state, "request_id", "")

    # Rate limiting
    rl_res = check_rate_limit(request)
    if rl_res is not None:
        return rl_res

    # Whitelist validation: rejects unknown names and path traversal attempts (../, /, etc.)
    if name not in SAMPLE_FILES:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Sample dataset '{name}' not found", "request_id": request_id},
        )

    filename = SAMPLE_FILES[name]
    sample_path = Path(settings.SAMPLES_DIR) / filename
    if not sample_path.is_file():
        return JSONResponse(
            status_code=404,
            content={
                "detail": f"Sample dataset file '{name}' not found on server",
                "request_id": request_id,
            },
        )

    content_str = sample_path.read_text(encoding="utf-8")
    lines = [ln for ln in content_str.splitlines() if ln.strip()]
    request.state.row_count = len(lines)

    try:
        pipeline_result = run_pipeline(content_str)
        return build_analysis_response(name, pipeline_result)
    except IngestError as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "request_id": request_id},
        )
    except Exception as exc:
        logger.exception(
            "Unexpected error analyzing sample '%s' [request_id=%s]: %s",
            name,
            request_id,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred.", "request_id": request_id},
        )



@router.post("/analyze", response_model=AnalysisResponse)
def analyze_orders(request: Request, file: UploadFile = File(...)) -> Any:
    """Analyze uploaded canonical CSV order history.

    Uploads are processed purely in-memory, never written to disk or logged.
    Executed in worker threadpool via plain def.
    """
    request_id = getattr(request.state, "request_id", "")

    # Rate limiting
    rl_res = check_rate_limit(request)
    if rl_res is not None:
        return rl_res

    # Check file extension and content type
    filename = file.filename or ""
    content_type = file.content_type or ""
    is_csv_name = filename.lower().endswith(".csv")
    is_csv_mime = content_type in (
        "text/csv",
        "text/plain",
        "application/vnd.ms-excel",
        "application/csv",
    )
    if not (is_csv_name or is_csv_mime):
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Invalid file format. Only CSV files (.csv or text/csv) are accepted.",
                "request_id": request_id,
            },
        )

    # Chunked read to enforce MAX_UPLOAD_MB and abort early
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    chunk_size = 64 * 1024
    chunks: list[bytes] = []
    total_bytes = 0

    while True:
        chunk = file.file.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"File exceeds maximum upload size of {settings.MAX_UPLOAD_MB} MB",
                    "request_id": request_id,
                },
            )
        chunks.append(chunk)

    raw_bytes = b"".join(chunks)

    # Empty file rejection
    if not raw_bytes.strip():
        return JSONResponse(
            status_code=422,
            content={"detail": "Uploaded file is empty", "request_id": request_id},
        )

    # Binary check (undecodable / null bytes)
    if b"\x00" in raw_bytes:
        return JSONResponse(
            status_code=422,
            content={"detail": "Binary file cannot be processed as CSV", "request_id": request_id},
        )

    try:
        content_str = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(
            status_code=422,
            content={"detail": "File encoding is not valid UTF-8", "request_id": request_id},
        )

    # Row count limit check
    lines = [ln for ln in content_str.splitlines() if ln.strip()]
    request.state.row_count = len(lines)
    if len(lines) > settings.MAX_ROWS:
        return JSONResponse(
            status_code=422,
            content={
                "detail": (
                    f"File contains {len(lines)} rows, which exceeds the limit "
                    f"of {settings.MAX_ROWS} rows."
                ),
                "request_id": request_id,
            },
        )


    try:
        pipeline_result = run_pipeline(content_str)
        return build_analysis_response("upload", pipeline_result)
    except IngestError as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "request_id": request_id},
        )
    except Exception as exc:
        logger.exception("Unexpected error analyzing upload [request_id=%s]: %s", request_id, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred.", "request_id": request_id},
        )
