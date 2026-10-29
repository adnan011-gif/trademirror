"""Narrative orchestration layer for TradeMirror.

Responsibility:
Constructs deterministic facts bundles from RankedResult and closed Trades, calls
configured LLM with strict grounding instructions, verifies generated text against
facts using the grounding verifier, and falls back seamlessly to deterministic templates
upon any validation error, timeout, or missing API key.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.llm.client import call_llm
from app.llm.templates import (
    generate_template_narrative,
    get_approved_rule,
)
from app.ranking import RankedResult
from app.verifier import VerificationReport, verify_narrative

if TYPE_CHECKING:
    import httpx

    from app.config import Settings
    from app.models import Trade

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "prompts" / "narrative_system.md"
)


class HabitNarrativeItem(BaseModel):
    """Schema for individual habit explanation in LLM output."""

    key: str
    explanation: str = Field(..., max_length=400)
    rule: str = Field(..., max_length=250)


class NarrativeSchema(BaseModel):
    """Schema for complete narrative output."""

    summary: str = Field(..., max_length=300)
    habits: list[HabitNarrativeItem]


@dataclass(frozen=True)
class Facts:
    """Deterministic, JSON-serializable facts bundle."""

    context: dict[str, Any]
    habits: list[dict[str, Any]]
    allowed_numbers: list[float]
    allowed_trade_ids: list[str]
    allowed_dates: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert Facts bundle to a clean serializable dictionary."""
        return {
            "context": self.context,
            "habits": self.habits,
            "allowed_numbers": self.allowed_numbers,
            "allowed_trade_ids": self.allowed_trade_ids,
            "allowed_dates": self.allowed_dates,
        }


@dataclass(frozen=True)
class NarrativeResult:
    """Result of narrative generation and grounding verification."""

    narrative: dict[str, Any]
    source: str  # "llm" | "template"
    fallback_reason: str | None
    verification: VerificationReport
    llm_attempts: int


def _extract_all_numbers(obj: Any, collected: set[float] | None = None) -> set[float]:
    """Recursively harvest all numbers from primitive structures or strings."""
    if collected is None:
        collected = set()

    if isinstance(obj, (int, float)):
        v = float(obj)
        collected.add(v)
        collected.add(abs(v))
    elif isinstance(obj, str):
        for m in re.finditer(r"\b\d+(?:\.\d+)?\b", obj):
            try:
                v = float(m.group(0))
                collected.add(v)
                collected.add(abs(v))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for val in obj.values():
            _extract_all_numbers(val, collected)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            _extract_all_numbers(item, collected)

    return collected


def build_facts(ranked: RankedResult, trades: list[Trade]) -> Facts:
    """Build deterministic, JSON-serializable facts bundle from ranked habits and trades.

    Args:
        ranked: RankedResult containing kept habits, dropped habits, and summary context.
        trades: Full list of closed Trade round-trips.

    Returns:
        Facts object containing context, kept habits, example trades, and allowed sets.
    """
    trades_by_id = {t.trade_id: t for t in trades}
    allowed_trade_ids_set: set[str] = set()
    allowed_dates_set: set[str] = set()

    context = {
        "n_trades": ranked.context.get("n_trades", len(trades)),
        "gross_pnl_inr": round(ranked.context.get("gross_pnl_inr", 0.0), 2),
        "gross_loss_inr": round(ranked.context.get("gross_loss_inr", 0.0), 2),
        "win_rate": round(ranked.context.get("win_rate", 0.0), 4),
        "total_attributed_cost_inr": round(ranked.total_attributed_cost_inr, 2),
    }

    habits_list: list[dict[str, Any]] = []

    for habit in ranked.habits:
        key = habit.key
        approved_rule = get_approved_rule(key, habit.metrics)

        # Flagged trades for this habit
        flagged_tids = habit.flagged_trade_ids
        for tid in flagged_tids:
            allowed_trade_ids_set.add(tid)

        habit_trades = [trades_by_id[tid] for tid in flagged_tids if tid in trades_by_id]
        # Sort largest loss first (gross_pnl ascending), ties by trade_id
        habit_trades.sort(key=lambda t: (t.gross_pnl, t.trade_id))
        example_trades_subset = habit_trades[:3]

        examples_serialized: list[dict[str, Any]] = []
        for et in example_trades_subset:
            t_date = et.entry_time.date().isoformat()
            allowed_dates_set.add(t_date)
            examples_serialized.append(
                {
                    "trade_id": et.trade_id,
                    "trading_date": t_date,
                    "symbol": et.symbol,
                    "instrument_type": et.instrument_type,
                    "strike": et.strike,
                    "direction": et.direction,
                    "hold_minutes": round(et.hold_minutes, 2),
                    "quantity": et.quantity,
                    "gross_pnl": round(et.gross_pnl, 2),
                }
            )

        habits_list.append(
            {
                "key": key,
                "name": habit.name,
                "attributed_cost_inr": round(habit.attributed_cost_inr, 2),
                "estimated_cost_inr": round(habit.estimated_cost_inr, 2),
                "overlap_share": round(habit.overlap_share, 4),
                "confidence": round(habit.confidence, 2),
                "metrics": habit.metrics,
                "formula_note": habit.formula_note,
                "approved_rule": approved_rule,
                "example_trades": examples_serialized,
            }
        )

    # Harvest all numbers appearing in the bundle and approved rules
    raw_numbers_set = _extract_all_numbers(context)
    raw_numbers_set.update(_extract_all_numbers(habits_list))

    # Add count of kept habits (e.g. 1, 2, 3)
    if habits_list:
        raw_numbers_set.add(float(len(habits_list)))

    # Convert to sorted list of floats
    allowed_numbers = sorted(raw_numbers_set)
    allowed_trade_ids = sorted(allowed_trade_ids_set)
    allowed_dates = sorted(allowed_dates_set)

    return Facts(
        context=context,
        habits=habits_list,
        allowed_numbers=allowed_numbers,
        allowed_trade_ids=allowed_trade_ids,
        allowed_dates=allowed_dates,
    )


def _load_system_prompt() -> str:
    """Load system prompt from file or fallback to embedded constant."""
    try:
        if SYSTEM_PROMPT_PATH.is_file():
            return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Could not read narrative_system.md: %s", e)

    return (
        "You are TradeMirror, an analytical trading coach explaining post-trade behavioral "
        "analysis. Use ONLY facts in the JSON. Output strict JSON with summary and habits."
    )


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code blocks around JSON responses."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def generate_narrative(
    ranked: RankedResult,
    trades: list[Trade],
    cfg: Settings = settings,
    transport: httpx.BaseTransport | None = None,
) -> NarrativeResult:
    """Generate and verify grounded narrative for ranked habits.

    Args:
        ranked: RankedResult from ranking module.
        trades: List of closed Trades.
        cfg: Settings configuration.
        transport: Optional transport override for test mocking.

    Returns:
        NarrativeResult with narrative dict, source, fallback_reason, verification, and attempts.
    """
    facts = build_facts(ranked, trades)

    # 1. Zero material habits -> deterministic template
    if not ranked.material or not ranked.habits:
        template_narrative = generate_template_narrative(ranked)
        report = verify_narrative(template_narrative, facts)
        if not report.passed:
            raise RuntimeError(
                f"Template narrative failed grounding verification: {report.failures}"
            )
        return NarrativeResult(
            narrative=template_narrative,
            source="template",
            fallback_reason=None,
            verification=report,
            llm_attempts=0,
        )

    # 2. No LLM key or provider is none -> deterministic template
    provider = (cfg.LLM_PROVIDER or "none").lower().strip()
    if provider == "none" or not cfg.LLM_API_KEY:
        template_narrative = generate_template_narrative(ranked)
        report = verify_narrative(template_narrative, facts)
        if not report.passed:
            raise RuntimeError(
                f"Template narrative failed grounding verification: {report.failures}"
            )
        return NarrativeResult(
            narrative=template_narrative,
            source="template",
            fallback_reason="no_llm_key",
            verification=report,
            llm_attempts=0,
        )

    # 3. Attempt LLM generation
    system_prompt = _load_system_prompt()
    facts_json = json.dumps(facts.to_dict(), indent=2)

    last_fallback_reason: str = "unknown"
    user_prompt = facts_json

    for attempt in range(1, 3):
        try:
            raw_response = call_llm(
                system=system_prompt,
                user=user_prompt,
                settings=cfg,
                transport=transport,
            )
        except Exception as exc:
            last_fallback_reason = f"llm_call_error: {exc}"
            logger.warning("LLM call attempt %d failed: %s", attempt, exc)
            break

        cleaned_json = _strip_markdown_fences(raw_response)

        try:
            data = json.loads(cleaned_json)
        except Exception as exc:
            last_fallback_reason = f"json_parse_error: {exc}"
            user_prompt = (
                f"{facts_json}\n\n"
                f"Your previous output failed JSON parsing with error: {exc}.\n"
                f"Output ONLY valid, parseable JSON conforming strictly to the facts."
            )
            continue

        try:
            validated = NarrativeSchema.model_validate(data)
            narrative_dict = validated.model_dump()
        except ValidationError as exc:
            last_fallback_reason = f"schema_validation_error: {exc}"
            user_prompt = (
                f"{facts_json}\n\n"
                f"Your previous output failed schema validation: {exc}.\n"
                f"Output strictly valid JSON with max 300 char summary, max 400 char explanations, "
                f"and max 250 char rules."
            )
            continue

        report = verify_narrative(narrative_dict, facts)
        if report.passed:
            return NarrativeResult(
                narrative=narrative_dict,
                source="llm",
                fallback_reason=None,
                verification=report,
                llm_attempts=attempt,
            )

        # Verification failed on this attempt
        failures_summary = "\n".join(f"- {f['field']}: {f['message']}" for f in report.failures[:5])
        last_fallback_reason = "verification_failed"
        user_prompt = (
            f"{facts_json}\n\n"
            f"Your previous output failed grounding verification with these errors:\n"
            f"{failures_summary}\n"
            f"Please strictly fix all ungrounded numbers, unknown trade IDs, and structure "
            f"issues. Rely solely on the provided numbers."
        )

    # 4. Fallback to template after failure / retry exhaustion
    template_narrative = generate_template_narrative(ranked)
    report = verify_narrative(template_narrative, facts)
    if not report.passed:
        raise RuntimeError(f"Template narrative failed grounding verification: {report.failures}")

    return NarrativeResult(
        narrative=template_narrative,
        source="template",
        fallback_reason=last_fallback_reason,
        verification=report,
        llm_attempts=attempt if "attempt" in locals() else 0,
    )


if __name__ == "__main__":
    from app.pipeline import run_pipeline

    if len(sys.argv) < 2:
        print("Usage: python -m app.narrative <path-to-csv>")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.is_file():
        print(f"Error: file not found: {csv_path}")
        sys.exit(1)

    pipeline_res = run_pipeline(csv_path)
    trades = pipeline_res.trades

    facts_bundle = build_facts(pipeline_res.ranked, trades)
    narrative_res = generate_narrative(pipeline_res.ranked, trades, settings)

    print("=" * 80)
    print(f"TRADEMIRROR NARRATIVE SMOKE RUN: {csv_path.name}")
    print("=" * 80)
    print("\n[FACTS BUNDLE CONTEXT]")
    print(json.dumps(facts_bundle.context, indent=2))
    print(f"\nAllowed numbers ({len(facts_bundle.allowed_numbers)} figures):")
    sample_ids = facts_bundle.allowed_trade_ids[:5]
    print(f"Allowed trade IDs ({len(facts_bundle.allowed_trade_ids)} IDs): {sample_ids}...")
    print(f"Allowed dates: {facts_bundle.allowed_dates}")

    print("\n[NARRATIVE RESULT]")
    print(f"Source: {narrative_res.source}")
    print(f"Fallback Reason: {narrative_res.fallback_reason}")
    print(f"LLM Attempts: {narrative_res.llm_attempts}")

    print("\n[NARRATIVE CONTENT]")
    print(json.dumps(narrative_res.narrative, indent=2))

    print("\n[VERIFICATION REPORT]")
    print(f"Passed: {narrative_res.verification.passed}")
    print(f"Checked Numbers: {len(narrative_res.verification.checked_numbers)}")
    print(f"Checked Trade IDs: {narrative_res.verification.checked_trade_ids}")
    print(f"Failures: {narrative_res.verification.failures}")
    print("=" * 80)
