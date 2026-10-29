"""Tests for habit ranking, greedy overlap attribution, and end-to-end pipeline."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.detectors.base import BaseDetector, HabitResult
from app.models import Order, Trade
from app.parsers.orders_csv import IngestError
from app.pipeline import PipelineResult, run_pipeline
from app.ranking import (
    MAX_HABITS,
    rank_habits,
)

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _make_dummy_trade(
    trade_id: str,
    gross_pnl: float,
    entry_time: datetime | None = None,
) -> Trade:
    """Helper to create dummy Trade objects for ranking context tests."""
    t0 = entry_time or datetime(2024, 10, 1, 9, 30, tzinfo=IST)
    return Trade(
        trade_id=trade_id,
        symbol="NIFTY24OCT25000CE",
        instrument_type="CE",
        strike=25000.0,
        expiry=date(2024, 10, 31),
        direction="LONG",
        entry_time=t0,
        exit_time=t0 + timedelta(minutes=20),
        entry_price=100.0,
        exit_price=100.0 + (gross_pnl / 75),
        quantity=75,
        lot_size=75,
        hold_minutes=20.0,
        gross_pnl=gross_pnl,
        entry_order_id=f"E_{trade_id}",
        exit_order_id=f"X_{trade_id}",
        is_partial_exit=False,
        is_add_on=False,
        trading_date=t0.date(),
    )


def _make_dummy_result(
    key: str,
    cost: float,
    confidence: float = 1.0,
    trade_ids: list[str] | None = None,
    name: str | None = None,
) -> HabitResult:
    """Helper to create dummy HabitResult objects for unit testing ranking."""
    ids = trade_ids if trade_ids is not None else [f"{key}_T{i}" for i in range(5)]
    return HabitResult(
        key=key,
        name=name or f"Habit {key.replace('_', ' ').title()}",
        flagged_trade_ids=sorted(ids),
        estimated_cost_inr=cost,
        confidence=confidence,
        metrics={},
        formula_note="Test note",
    )


# =====================================================================
# Unit Tests for rank_habits
# =====================================================================


def test_ranking_ordering_by_cost_and_tiebreak_by_key() -> None:
    """Habits are sorted descending by cost; ties broken alphabetically by key."""
    trades = [_make_dummy_trade("T1", 100.0), _make_dummy_trade("T2", -200.0)]

    # 4 habits: two tie at 5000, one at 8000, one at 2000
    r_rev = _make_dummy_result("revenge_trading", 5000.0)
    r_hold = _make_dummy_result("holding_losers", 5000.0)
    r_over = _make_dummy_result("overtrading", 8000.0)
    r_size = _make_dummy_result("oversizing", 2000.0)

    res = rank_habits([r_rev, r_hold, r_over, r_size], trades)

    assert res.material is True
    assert len(res.habits) == MAX_HABITS  # Cap at 3
    # Top 1: overtrading (8000)
    assert res.habits[0].key == "overtrading"
    assert res.habits[0].attributed_cost_inr == 8000.0

    # Tied at 5000: 'holding_losers' < 'revenge_trading' alphabetically
    assert res.habits[1].key == "holding_losers"
    assert res.habits[2].key == "revenge_trading"


def test_ranking_cap_at_three_habits() -> None:
    """When more than 3 habits qualify, only top 3 are kept."""
    trades = [_make_dummy_trade("T1", -500.0)]
    results = [
        _make_dummy_result("habit_1", 10000.0),
        _make_dummy_result("habit_2", 8000.0),
        _make_dummy_result("habit_3", 6000.0),
        _make_dummy_result("habit_4", 4000.0),
        _make_dummy_result("habit_5", 2000.0),
    ]

    res = rank_habits(results, trades)
    assert len(res.habits) == 3
    assert [h.key for h in res.habits] == ["habit_1", "habit_2", "habit_3"]


def test_ranking_drops_below_thresholds_with_reasons() -> None:
    """Habits below MIN_CONFIDENCE (0.25) or MIN_COST_INR (500) are dropped with reasons."""
    trades = [_make_dummy_trade("T1", -1000.0)]

    r_ok = _make_dummy_result("habit_ok", 2500.0, confidence=0.8)
    r_low_conf = _make_dummy_result("habit_low_conf", 5000.0, confidence=0.20)
    r_low_cost = _make_dummy_result("habit_low_cost", 350.0, confidence=0.90)
    r_low_both = _make_dummy_result("habit_low_both", 100.0, confidence=0.10)

    res = rank_habits([r_ok, r_low_conf, r_low_cost, r_low_both], trades)

    assert len(res.habits) == 1
    assert res.habits[0].key == "habit_ok"

    dropped_keys = {d["key"]: d["reason"] for d in res.dropped}
    assert "habit_low_conf" in dropped_keys
    assert "confidence" in dropped_keys["habit_low_conf"]

    assert "habit_low_cost" in dropped_keys
    assert "estimated cost" in dropped_keys["habit_low_cost"]

    assert "habit_low_both" in dropped_keys
    assert "confidence" in dropped_keys["habit_low_both"]
    assert "estimated cost" in dropped_keys["habit_low_both"]


def test_ranking_overlap_partial_and_total_deduplication() -> None:
    """Overlaps reduce attributed cost proportionally; total is sum of attributed costs."""
    trades = [_make_dummy_trade("T1", -1000.0)]

    # Habit A: 4 trade IDs, cost 4000 (1000/trade). Rank 1.
    r_a = _make_dummy_result("habit_a", 4000.0, trade_ids=["T01", "T02", "T03", "T04"])
    # Habit B: 4 trade IDs (T03, T04, T05, T06), cost 2000. Shares 2 of 4 IDs with A (50% overlap).
    # Attributed cost = 2000 * (1 - 2/4) = 1000.0.
    r_b = _make_dummy_result("habit_b", 2000.0, trade_ids=["T03", "T04", "T05", "T06"])
    # Habit C: 2 trade IDs (T01, T02), cost 1500. Shares 2 of 2 IDs with A (100% overlap).
    # Attributed cost = 1500 * (1 - 2/2) = 0.0.
    r_c = _make_dummy_result("habit_c", 1500.0, trade_ids=["T01", "T02"])

    res = rank_habits([r_a, r_b, r_c], trades)

    assert len(res.habits) == 3

    h_a = next(h for h in res.habits if h.key == "habit_a")
    assert h_a.attributed_cost_inr == 4000.0
    assert h_a.overlap_share == 0.0

    h_b = next(h for h in res.habits if h.key == "habit_b")
    assert abs(h_b.attributed_cost_inr - 1000.0) < 0.01
    assert abs(h_b.overlap_share - 0.50) < 0.01

    h_c = next(h for h in res.habits if h.key == "habit_c")
    assert h_c.attributed_cost_inr == 0.0
    assert abs(h_c.overlap_share - 1.00) < 0.01

    # Total attributed cost is the sum of kept attributed costs: 4000 + 1000 + 0 = 5000.0
    assert abs(res.total_attributed_cost_inr - 5000.0) < 0.01

    # Overlaps recorded
    pair_habits = [o["habits"] for o in res.overlaps]
    assert ["habit_a", "habit_b"] in pair_habits
    assert ["habit_a", "habit_c"] in pair_habits


def test_ranking_materiality_zero_and_one_habit() -> None:
    """Zero kept habits -> material False with reason. One kept habit -> material True."""
    trades = [_make_dummy_trade("T1", 500.0), _make_dummy_trade("T2", -200.0)]

    # Zero results
    res_empty = rank_habits([], trades)
    assert res_empty.material is False
    assert res_empty.reason == "No habit cleared the evidence bar this month"
    assert res_empty.total_attributed_cost_inr == 0.0
    assert len(res_empty.habits) == 0

    # One qualifying result
    r_one = _make_dummy_result("habit_one", 1200.0, confidence=0.6)
    res_one = rank_habits([r_one], trades)
    assert res_one.material is True
    assert res_one.reason is None
    assert len(res_one.habits) == 1
    assert res_one.total_attributed_cost_inr == 1200.0

    # Summary context is correctly populated
    assert res_one.context["n_trades"] == 2
    assert res_one.context["gross_pnl_inr"] == 300.0
    assert res_one.context["gross_loss_inr"] == 200.0
    assert res_one.context["win_rate"] == 0.5


def test_ranking_determinism() -> None:
    """Repeated calls to rank_habits with the same inputs return identical results."""
    trades = [_make_dummy_trade(f"T{i}", 100.0 * (1 if i % 2 == 0 else -1)) for i in range(10)]
    results = [
        _make_dummy_result("habit_x", 3000.0, trade_ids=["T1", "T3"]),
        _make_dummy_result("habit_y", 2500.0, trade_ids=["T3", "T5"]),
    ]

    r1 = rank_habits(results, trades)
    r2 = rank_habits(results, trades)

    assert r1.material == r2.material
    assert r1.total_attributed_cost_inr == r2.total_attributed_cost_inr
    assert [h.key for h in r1.habits] == [h.key for h in r2.habits]
    assert [h.attributed_cost_inr for h in r1.habits] == [h.attributed_cost_inr for h in r2.habits]


# =====================================================================
# Unit Tests for run_pipeline error handling
# =====================================================================


class _CrashingDetector(BaseDetector):
    """Mock detector that unconditionally raises an exception."""

    key = "crashing_detector"

    def detect(self, trades: list[Trade]) -> HabitResult | None:
        raise RuntimeError("Simulated detector internal explosion")


def test_pipeline_captures_detector_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """A detector raising an exception does NOT crash the pipeline; error is recorded."""
    import app.pipeline as pl

    # Patch ALL_DETECTORS to include our crashing detector alongside normal detectors
    crashing = _CrashingDetector()
    monkeypatch.setattr(pl, "ALL_DETECTORS", [crashing])

    # Run pipeline with clean order list
    dummy_orders = [
        Order(
            order_id="ORD1",
            timestamp=datetime(2024, 10, 1, 9, 30, tzinfo=IST),
            symbol="NIFTY24OCT25000CE",
            instrument_type="CE",
            strike=25000.0,
            expiry=date(2024, 10, 31),
            side="BUY",
            quantity=75,
            lot_size=75,
            price=100.0,
            status="COMPLETE",
        ),
        Order(
            order_id="ORD2",
            timestamp=datetime(2024, 10, 1, 9, 50, tzinfo=IST),
            symbol="NIFTY24OCT25000CE",
            instrument_type="CE",
            strike=25000.0,
            expiry=date(2024, 10, 31),
            side="SELL",
            quantity=75,
            lot_size=75,
            price=120.0,
            status="COMPLETE",
        ),
    ]

    result = pl.run_pipeline(dummy_orders)

    # Pipeline completed without raising RuntimeError
    assert isinstance(result, PipelineResult)
    assert len(result.detector_errors) == 1
    assert result.detector_errors[0]["detector"] == "crashing_detector"
    assert "Simulated detector internal explosion" in result.detector_errors[0]["error"]
    assert result.ranked.material is False


def test_pipeline_ingest_error_propagates() -> None:
    """IngestError from corrupt CSV schema propagates unchanged."""
    corrupt_csv = "not_a_valid_header,something_else\n1,2"
    with pytest.raises(IngestError):
        run_pipeline(corrupt_csv)


# =====================================================================
# End-to-End Tests on Committed Datasets
# =====================================================================


def test_pipeline_clean_dataset_not_material() -> None:
    """clean.csv pipeline result must have material = False and 0 kept habits."""
    csv_path = Path("data/datasets/clean.csv")
    res = run_pipeline(csv_path)

    assert res.ranked.material is False
    assert len(res.ranked.habits) == 0
    assert res.ranked.reason == "No habit cleared the evidence bar this month"
    assert len(res.detector_errors) == 0


@pytest.mark.parametrize(
    "dataset_name,expected_habit",
    [
        ("single_holding_losers", "holding_losers"),
        ("single_revenge_trading", "revenge_trading"),
        ("single_overtrading", "overtrading"),
        ("single_oversizing", "oversizing"),
        ("single_averaging_down", "averaging_down"),
    ],
)
def test_pipeline_single_habit_datasets_rank_one(
    dataset_name: str, expected_habit: str
) -> None:
    """On single_* datasets, the planted habit is rank 1 and the ONLY habit kept."""
    csv_path = Path(f"data/datasets/{dataset_name}.csv")
    res = run_pipeline(csv_path)

    assert res.ranked.material is True
    assert len(res.ranked.habits) == 1, (
        f"Expected exactly 1 kept habit on {dataset_name}, got {[h.key for h in res.ranked.habits]}"
    )
    assert res.ranked.habits[0].key == expected_habit
    assert res.ranked.habits[0].attributed_cost_inr == res.ranked.habits[0].estimated_cost_inr
    assert len(res.detector_errors) == 0


def test_pipeline_mixed_dataset_ranks_and_overlaps() -> None:
    """mixed.csv keeps exactly the 3 planted habits with correct ranks and overlap attribution."""
    csv_path = Path("data/datasets/mixed.csv")
    res = run_pipeline(csv_path)

    assert res.ranked.material is True
    kept_keys = [h.key for h in res.ranked.habits]
    assert kept_keys == ["holding_losers", "revenge_trading", "overtrading"], (
        f"Expected ['holding_losers', 'revenge_trading', 'overtrading'], got {kept_keys}"
    )

    h_hl = res.ranked.habits[0]
    h_rt = res.ranked.habits[1]
    h_ot = res.ranked.habits[2]

    # Rank 1: holding_losers (cost 97,841.20, attr 97,841.20, overlap 0.0%)
    assert h_hl.key == "holding_losers"
    assert h_hl.attributed_cost_inr == h_hl.estimated_cost_inr
    assert h_hl.overlap_share == 0.0

    # Rank 2: revenge_trading (shares 5 of 12 trades with holding_losers, attr cost lower)
    assert h_rt.key == "revenge_trading"
    assert h_rt.attributed_cost_inr < h_rt.estimated_cost_inr
    assert abs(h_rt.overlap_share - (5 / 12)) < 0.01
    assert abs(h_rt.attributed_cost_inr - 28103.25) < 0.01

    # Rank 3: overtrading (no overlap with earlier habits)
    assert h_ot.key == "overtrading"
    assert h_ot.attributed_cost_inr == h_ot.estimated_cost_inr
    assert h_ot.overlap_share == 0.0

    # Overlaps list
    assert len(res.ranked.overlaps) == 1
    assert res.ranked.overlaps[0]["habits"] == ["holding_losers", "revenge_trading"]
    assert len(res.ranked.overlaps[0]["shared_trade_ids"]) == 5

    # Total attributed cost
    expected_total = h_hl.attributed_cost_inr + h_rt.attributed_cost_inr + h_ot.attributed_cost_inr
    assert abs(res.ranked.total_attributed_cost_inr - expected_total) < 0.01


def test_pipeline_messy_dataset_completes_with_warnings() -> None:
    """messy.csv completes through pipeline, has ingest warnings, and 0 detector errors."""
    csv_path = Path("data/datasets/messy.csv")
    res = run_pipeline(csv_path)

    assert res.ranked.material is True
    assert len(res.ingest_warnings) > 0, "messy.csv must have ingest warnings"
    assert len(res.detector_errors) == 0, f"Expected 0 detector errors, got {res.detector_errors}"
