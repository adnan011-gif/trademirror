"""Tests for LLM client wrapper, narrative orchestrator, and template consistency."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.config import Settings
from app.detectors import ALL_DETECTORS
from app.llm.templates import generate_template_narrative
from app.narrative import (
    build_facts,
    generate_narrative,
)
from app.pairing import pair_orders
from app.parsers.orders_csv import parse_orders
from app.ranking import RankedHabit, RankedResult, rank_habits
from app.verifier import verify_narrative

DATASETS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "datasets"
COMMITTED_DATASETS = sorted(DATASETS_DIR.glob("*.csv"))


def _make_dummy_ranked_and_trades() -> tuple[RankedResult, list[Any]]:
    """Helper returning a standard RankedResult fixture for LLM orchestration tests."""
    from datetime import datetime, timedelta, timezone

    from app.models import Trade

    ist = timezone(timedelta(hours=5, minutes=30))
    t1 = Trade(
        trade_id="P0010",
        symbol="NIFTY",
        instrument_type="CE",
        strike=25000.0,
        expiry=datetime(2024, 10, 31, tzinfo=ist).date(),
        direction="LONG",
        entry_time=datetime(2024, 10, 1, 9, 30, tzinfo=ist),
        exit_time=datetime(2024, 10, 1, 10, 26, tzinfo=ist),
        entry_price=100.0,
        exit_price=50.0,
        quantity=50,
        lot_size=50,
        entry_order_id="ORD001",
        exit_order_id="ORD002",
        is_partial_exit=False,
        is_add_on=False,
        trading_date=datetime(2024, 10, 1, tzinfo=ist).date(),
        gross_pnl=-2500.0,
        hold_minutes=56.0,
    )
    trades = [t1]

    habit1 = RankedHabit(
        key="holding_losers",
        name="Holding losing trades",
        flagged_trade_ids=["P0010"],
        estimated_cost_inr=97841.20,
        confidence=0.83,
        metrics={
            "median_winner_hold_min": 21.0,
            "median_loser_hold_min": 31.0,
            "hold_ratio": 1.48,
            "flagged_count": 33,
            "flagged_median_hold_min": 56.0,
            "flagged_hold_ratio": 2.67,
            "baseline_loss_inr": 1000.0,
        },
        formula_note="Test note",
        attributed_cost_inr=97841.20,
        overlap_share=0.0,
    )

    ranked = RankedResult(
        habits=[habit1],
        total_attributed_cost_inr=97841.20,
        overlaps=[],
        dropped=[],
        material=True,
        reason=None,
        context={
            "n_trades": 1,
            "gross_pnl_inr": -2500.0,
            "gross_loss_inr": 2500.0,
            "win_rate": 0.0,
        },
    )
    return ranked, trades


def test_no_key_makes_zero_http_calls_and_returns_template() -> None:
    """Verifies that missing API key or provider 'none' returns template without HTTP call."""
    ranked, trades = _make_dummy_ranked_and_trades()
    cfg = Settings(LLM_API_KEY=None, LLM_PROVIDER="none")

    result = generate_narrative(ranked, trades, cfg=cfg)

    assert result.source == "template"
    assert result.fallback_reason == "no_llm_key"
    assert result.llm_attempts == 0
    assert result.verification.passed is True
    assert "holding_losers" in result.narrative["habits"][0]["key"]


def test_good_mocked_llm_response_gives_source_llm() -> None:
    """Verifies that a valid, grounded JSON response from LLM yields source 'llm'."""
    ranked, trades = _make_dummy_ranked_and_trades()
    cfg = Settings(LLM_API_KEY="test_key", LLM_PROVIDER="gemini", LLM_MODEL="gemini-1.5-flash")

    valid_json = json.dumps(
        {
            "summary": "Your trading was impacted by Holding losing trades costing ₹97,841.20.",
            "habits": [
                {
                    "key": "holding_losers",
                    "explanation": (
                        "Winning trades had a median hold of 21.0 minutes, while "
                        "losing trades were held for 56.0 minutes. This cost "
                        "₹97,841.20 across 33 trades."
                    ),
                    "rule": (
                        "Set a hard time stop to exit any losing trade within "
                        "30 minutes of entry."
                    ),
                }
            ],
        }
    )

    def handle(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"candidates": [{"content": {"parts": [{"text": valid_json}]}}]})
        return httpx.Response(200, content=content.encode("utf-8"))

    transport = httpx.MockTransport(handle)
    result = generate_narrative(ranked, trades, cfg=cfg, transport=transport)

    assert result.source == "llm"
    assert result.fallback_reason is None
    assert result.llm_attempts == 1
    assert result.verification.passed is True


def test_invalid_json_then_good_second_response_gives_source_llm_attempts_two() -> None:
    """Verifies that bad JSON on attempt 1 retries once and succeeds on attempt 2."""
    ranked, trades = _make_dummy_ranked_and_trades()
    cfg = Settings(LLM_API_KEY="test_key", LLM_PROVIDER="gemini", LLM_MODEL="gemini-1.5-flash")

    valid_json = json.dumps(
        {
            "summary": "Impacted by Holding losing trades costing ₹97,841.20.",
            "habits": [
                {
                    "key": "holding_losers",
                    "explanation": (
                        "Winning trades had median hold of 21.0 minutes versus "
                        "56.0 minutes for losers. Holding 33 trades cost ₹97,841.20."
                    ),
                    "rule": "Set a hard time stop to exit any losing trade within 30 minutes.",
                }
            ],
        }
    )

    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            # First attempt: invalid broken JSON
            return httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "not { json"}]}}]}
            )
        # Second attempt: valid JSON
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": valid_json}]}}]}
        )

    transport = httpx.MockTransport(handle)
    result = generate_narrative(ranked, trades, cfg=cfg, transport=transport)

    assert calls == 2
    assert result.source == "llm"
    assert result.llm_attempts == 2
    assert result.verification.passed is True


def test_invalid_twice_falls_back_with_reason() -> None:
    """Verifies that 2 failed parse attempts gracefully fall back to template narrative."""
    ranked, trades = _make_dummy_ranked_and_trades()
    cfg = Settings(LLM_API_KEY="test_key", LLM_PROVIDER="gemini", LLM_MODEL="gemini-1.5-flash")

    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "not json at all"}]}}]}
        )

    transport = httpx.MockTransport(handle)
    result = generate_narrative(ranked, trades, cfg=cfg, transport=transport)

    assert calls == 2
    assert result.source == "template"
    assert "json_parse_error" in (result.fallback_reason or "")
    assert result.verification.passed is True


def test_verification_failure_triggers_one_retry_with_failure_details() -> None:
    """Verifies grounding failure triggers exactly 1 retry containing failure messages."""
    ranked, trades = _make_dummy_ranked_and_trades()
    cfg = Settings(LLM_API_KEY="test_key", LLM_PROVIDER="gemini", LLM_MODEL="gemini-1.5-flash")

    bad_json = json.dumps(
        {
            "summary": "Made up loss of ₹99,999.",
            "habits": [
                {
                    "key": "holding_losers",
                    "explanation": "Cost ₹99,999 across 33 trades.",
                    "rule": "Set a hard time stop to exit within 30 minutes.",
                }
            ],
        }
    )

    good_json = json.dumps(
        {
            "summary": "Impacted by Holding losing trades costing ₹97,841.20.",
            "habits": [
                {
                    "key": "holding_losers",
                    "explanation": "Cost ₹97,841.20 across 33 trades with median 56.0 minutes.",
                    "rule": "Set a hard time stop to exit within 30 minutes.",
                }
            ],
        }
    )

    received_prompts: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        user_msg = body["contents"][0]["parts"][0]["text"]
        received_prompts.append(user_msg)

        if len(received_prompts) == 1:
            return httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": bad_json}]}}]}
            )
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": good_json}]}}]}
        )

    transport = httpx.MockTransport(handle)
    result = generate_narrative(ranked, trades, cfg=cfg, transport=transport)

    assert len(received_prompts) == 2
    # Verify the retry prompt explicitly includes the grounding failure notification
    assert (
        "grounding verification" in received_prompts[1]
        or "ungrounded_number" in received_prompts[1]
    )
    assert result.source == "llm"
    assert result.llm_attempts == 2


def test_http_500_and_timeout_fall_back_without_raising() -> None:
    """Verifies HTTP errors and network timeouts fall back to template without raising."""
    ranked, trades = _make_dummy_ranked_and_trades()
    cfg = Settings(LLM_API_KEY="test_key", LLM_PROVIDER="gemini", LLM_MODEL="gemini-1.5-flash")

    # Case 1: HTTP 500 error
    def handle_500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    res_500 = generate_narrative(ranked, trades, cfg=cfg, transport=httpx.MockTransport(handle_500))
    assert res_500.source == "template"
    assert "llm_call_error" in (res_500.fallback_reason or "")

    # Case 2: Timeout exception
    def handle_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Connection timed out")

    res_timeout = generate_narrative(
        ranked, trades, cfg=cfg, transport=httpx.MockTransport(handle_timeout)
    )
    assert res_timeout.source == "template"
    assert "llm_call_error" in (res_timeout.fallback_reason or "")


def test_never_more_than_two_calls() -> None:
    """Verifies that under no circumstance does the orchestrator make > 2 LLM calls."""
    ranked, trades = _make_dummy_ranked_and_trades()
    cfg = Settings(LLM_API_KEY="test_key", LLM_PROVIDER="gemini", LLM_MODEL="gemini-1.5-flash")

    call_count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "not valid json"}]}}]}
        )

    transport = httpx.MockTransport(handle)
    res = generate_narrative(ranked, trades, cfg=cfg, transport=transport)

    assert call_count <= 2
    assert res.source == "template"


def test_zero_habits_makes_no_llm_call() -> None:
    """Verifies that non-material months make 0 LLM calls and return 'nothing material'."""
    ranked = RankedResult(
        habits=[],
        total_attributed_cost_inr=0.0,
        overlaps=[],
        dropped=[],
        material=False,
        reason="No habit cleared the evidence bar this month",
        context={
            "n_trades": 100,
            "gross_pnl_inr": 50000.0,
            "gross_loss_inr": 20000.0,
            "win_rate": 0.6,
        },
    )
    cfg = Settings(LLM_API_KEY="test_key", LLM_PROVIDER="gemini")

    result = generate_narrative(ranked, trades=[], cfg=cfg)

    assert result.source == "template"
    assert result.llm_attempts == 0
    assert result.narrative["summary"] == "No behavioral habit cleared the evidence bar this month."
    assert result.narrative["habits"] == []
    assert result.verification.passed is True


@pytest.mark.parametrize("csv_path", COMMITTED_DATASETS, ids=lambda p: p.name)
def test_self_consistency_template_passes_on_all_committed_datasets(csv_path: Path) -> None:
    """Parametrised self-consistency proof across ALL committed datasets."""
    ingest = parse_orders(csv_path)
    pairing = pair_orders(ingest.orders)
    detector_outputs = [d.detect(pairing.trades) for d in ALL_DETECTORS]
    active_results = [d for d in detector_outputs if d is not None]
    ranked = rank_habits(active_results, pairing.trades)

    facts = build_facts(ranked, pairing.trades)
    template_narrative = generate_template_narrative(ranked)
    rep = verify_narrative(template_narrative, facts)

    # Every template narrative must strictly pass verification
    assert rep.passed is True, (
        f"Dataset {csv_path.name} template failed verification: {rep.failures}"
    )

    if csv_path.name == "clean.csv":
        assert ranked.material is False
        assert (
            template_narrative["summary"]
            == "No behavioral habit cleared the evidence bar this month."
        )
        assert template_narrative["habits"] == []
    else:
        assert ranked.material is True
        assert len(template_narrative["habits"]) > 0


def test_facts_bundle_determinism() -> None:
    """Asserts that identical inputs produce byte-identical facts JSON."""
    csv_path = DATASETS_DIR / "mixed.csv"
    ingest = parse_orders(csv_path)
    pairing = pair_orders(ingest.orders)
    detector_outputs = [d.detect(pairing.trades) for d in ALL_DETECTORS]
    active_results = [d for d in detector_outputs if d is not None]
    ranked = rank_habits(active_results, pairing.trades)

    facts1 = build_facts(ranked, pairing.trades)
    facts2 = build_facts(ranked, pairing.trades)

    json1 = json.dumps(facts1.to_dict(), sort_keys=True, indent=2)
    json2 = json.dumps(facts2.to_dict(), sort_keys=True, indent=2)

    assert json1 == json2
