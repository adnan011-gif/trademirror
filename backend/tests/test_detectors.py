"""Tests for behavioral habit detectors.

Organized per detector:
1. HoldingLosersDetector
(Later steps append further detector test suites)
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.detectors.holding_losers import (
    HoldingLosersDetector,
)
from app.models import Trade
from app.pairing import pair_orders
from app.parsers.orders_csv import parse_orders

from data.generator import generate_dataset_in_memory

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


# =====================================================================
# SECTION 1: HoldingLosersDetector Tests
# =====================================================================


def _make_trade(
    trade_id: str,
    gross_pnl: float,
    hold_minutes: float,
    entry_order_id: str = "O_ENTRY",
    exit_order_id: str = "O_EXIT",
    trading_date: date | None = None,
) -> Trade:
    """Helper to create Trade objects for detector tests."""
    t_date = trading_date or date(2024, 10, 1)
    base_time = datetime(t_date.year, t_date.month, t_date.day, 10, 0, tzinfo=IST)
    exit_time = base_time + timedelta(minutes=hold_minutes)
    return Trade(
        trade_id=trade_id,
        symbol="NIFTY24OCT25000CE",
        instrument_type="CE",
        strike=25000.0,
        expiry=date(2024, 10, 31),
        direction="LONG",
        entry_time=base_time,
        exit_time=exit_time,
        entry_price=100.0,
        exit_price=100.0 + (gross_pnl / 75.0),
        quantity=75,
        lot_size=75,
        hold_minutes=hold_minutes,
        gross_pnl=gross_pnl,
        entry_order_id=entry_order_id,
        exit_order_id=exit_order_id,
        is_partial_exit=False,
        is_add_on=False,
        trading_date=t_date,
    )


def test_holding_losers_fires_on_constructed_case() -> None:
    """Verify detector fires on constructed case with exact hand-calculated metrics."""
    # 6 winners: hold times 20, 20, 20, 20, 20, 20 -> median = 20.0 min
    winners = [_make_trade(f"W{i}", gross_pnl=1500.0, hold_minutes=20.0) for i in range(1, 7)]

    # 6 normal losers: hold times 22 min, pnl = -1000.0
    normal_losers = [
        _make_trade(f"L{i}", gross_pnl=-1000.0, hold_minutes=22.0) for i in range(1, 7)
    ]

    # 4 flagged losers: hold times 50 min (> 2x 20 = 40), pnl = -3000.0
    flagged_losers = [
        _make_trade(f"F{i}", gross_pnl=-3000.0, hold_minutes=50.0) for i in range(1, 5)
    ]

    trades = winners + normal_losers + flagged_losers
    detector = HoldingLosersDetector()
    res = detector.detect(trades)

    assert res is not None
    assert res.key == "holding_losers"
    assert res.name == "Holding losing trades too long"
    assert res.flagged_trade_ids == ["F1", "F2", "F3", "F4"]

    # Baseline loss: median of normal losers = 1000.0
    # Excess per flagged loser = 3000 - 1000 = 2000.0. Total = 4 * 2000 = 8000.0
    assert res.estimated_cost_inr == 8000.0
    assert res.metrics["flagged_count"] == 4
    assert res.metrics["baseline_loss_inr"] == 1000.0
    assert res.metrics["median_winner_hold_min"] == 20.0


def test_holding_losers_minimum_sample_guards() -> None:
    """Verify None when winners < 5 or losers < 5."""
    detector = HoldingLosersDetector()

    # 4 winners (< 5), 10 losers
    trades_few_winners = (
        [_make_trade(f"W{i}", 1000.0, 20.0) for i in range(4)]
        + [_make_trade(f"L{i}", -2000.0, 60.0) for i in range(10)]
    )
    assert detector.detect(trades_few_winners) is None

    # 10 winners, 4 losers (< 5)
    trades_few_losers = (
        [_make_trade(f"W{i}", 1000.0, 20.0) for i in range(10)]
        + [_make_trade(f"L{i}", -2000.0, 60.0) for i in range(4)]
    )
    assert detector.detect(trades_few_losers) is None


def test_holding_losers_no_disparity_returns_none() -> None:
    """Verify None when losers held about as long as winners."""
    detector = HoldingLosersDetector()
    winners = [_make_trade(f"W{i}", 1000.0, 25.0) for i in range(10)]
    losers = [_make_trade(f"L{i}", -1000.0, 25.0) for i in range(10)]
    assert detector.detect(winners + losers) is None


def test_holding_losers_effect_size_guards() -> None:
    """Verify None when flagged count < MIN_FLAGGED or hold ratio < MEDIAN_RATIO_MIN."""
    detector = HoldingLosersDetector()
    winners = [_make_trade(f"W{i}", 1000.0, 20.0) for i in range(10)]

    # Only 2 flagged (< MIN_FLAGGED = 3)
    losers_2_flagged = (
        [_make_trade(f"L{i}", -1000.0, 20.0) for i in range(8)]
        + [_make_trade(f"F{i}", -2000.0, 60.0) for i in range(2)]
    )
    assert detector.detect(winners + losers_2_flagged) is None

    # Ratio check: hold ratio < MEDIAN_RATIO_MIN
    # 10 winners (hold=20), 10 losers with median hold 21 min (ratio 1.05 < 1.10)
    losers_low_ratio = (
        [_make_trade(f"L{i}", -1000.0, 20.0) for i in range(7)]
        + [_make_trade(f"F{i}", -2000.0, 50.0) for i in range(3)]
    )
    assert detector.detect(winners + losers_low_ratio) is None


def test_holding_losers_few_non_flagged_fallback_baseline() -> None:
    """Verify fewer than 3 non-flagged losers falls back to all-losers baseline."""
    detector = HoldingLosersDetector()
    winners = [_make_trade(f"W{i}", 1000.0, 20.0) for i in range(6)]

    # 2 non-flagged losers (pnl=-500, hold=25) and 4 flagged losers (pnl=-2000, hold=60)
    # Total losers = 6. All-losers median |pnl|: [-500, -500, -2000, -2000, -2000, -2000] -> 2000.0
    non_flagged = [_make_trade(f"N{i}", -500.0, 25.0) for i in range(2)]
    flagged = [_make_trade(f"F{i}", -2000.0, 60.0) for i in range(4)]
    res = detector.detect(winners + non_flagged + flagged)

    # All-losers median is 2000.0; max(0, 2000 - 2000) = 0 -> estimated cost <= 0 returns None
    assert res is None


def test_holding_losers_zero_pnl_trades_ignored() -> None:
    """Verify break-even trades with gross_pnl == 0 are ignored."""
    detector = HoldingLosersDetector()
    winners = [_make_trade(f"W{i}", 1000.0, 20.0) for i in range(6)]
    losers = (
        [_make_trade(f"L{i}", -1000.0, 22.0) for i in range(6)]
        + [_make_trade(f"F{i}", -3000.0, 50.0) for i in range(4)]
    )
    zeros = [_make_trade(f"Z{i}", 0.0, 100.0) for i in range(5)]

    res_without_zeros = detector.detect(winners + losers)
    res_with_zeros = detector.detect(winners + losers + zeros)

    assert res_without_zeros is not None
    assert res_with_zeros is not None
    assert res_with_zeros.estimated_cost_inr == res_without_zeros.estimated_cost_inr
    assert res_with_zeros.metrics == res_without_zeros.metrics


def test_holding_losers_on_benchmark_datasets() -> None:
    """Verify clean.csv returns None, and single_holding_losers/mixed fire."""
    detector = HoldingLosersDetector()

    # 1. clean.csv must return None
    clean_trades = pair_orders(parse_orders(Path("data/datasets/clean.csv")).orders).trades
    assert detector.detect(clean_trades) is None, "Holding losers detector fired on clean.csv!"

    # 2. single_holding_losers.csv must fire
    single_trades = pair_orders(
        parse_orders(Path("data/datasets/single_holding_losers.csv")).orders
    ).trades
    single_res = detector.detect(single_trades)
    assert single_res is not None, "Failed to detect holding losers in single_holding_losers.csv"

    with open(Path("data/ground_truth/single_holding_losers.json"), encoding="utf-8") as f:
        single_gt = json.load(f)["habits"]["holding_losers"]

    gt_entry_oids = set(single_gt["entry_order_ids"])
    flagged_entry_oids = {
        t.entry_order_id for t in single_trades if t.trade_id in single_res.flagged_trade_ids
    }

    tp = len(flagged_entry_oids & gt_entry_oids)
    fp = len(flagged_entry_oids - gt_entry_oids)
    fn = len(gt_entry_oids - flagged_entry_oids)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    print("\n--- single_holding_losers.csv ---")
    print(f"Precision: {precision:.3f} (threshold >= 0.8)")
    print(f"Recall: {recall:.3f} (threshold >= 0.6)")
    print(f"Estimated Cost: ₹{single_res.estimated_cost_inr:,.2f}")
    print(f"Injected Loss:  ₹{single_gt['injected_loss_inr']:,.2f}")

    assert precision >= 0.8, f"Precision {precision:.3f} < 0.8"
    assert recall >= 0.6, f"Recall {recall:.3f} < 0.6"

    # Cost sanity: within 0.5x to 2.0x of ground-truth injected_loss_inr
    cost_ratio = single_res.estimated_cost_inr / single_gt["injected_loss_inr"]
    assert 0.5 <= cost_ratio <= 2.0, f"Cost ratio {cost_ratio:.2f} outside [0.5, 2.0]"

    # 3. mixed.csv must fire
    mixed_trades = pair_orders(parse_orders(Path("data/datasets/mixed.csv")).orders).trades
    mixed_res = detector.detect(mixed_trades)
    assert mixed_res is not None, "Failed to detect holding losers in mixed.csv"

    with open(Path("data/ground_truth/mixed.json"), encoding="utf-8") as f:
        mixed_gt = json.load(f)["habits"]["holding_losers"]

    m_gt_oids = set(mixed_gt["entry_order_ids"])
    m_flagged_oids = {
        t.entry_order_id for t in mixed_trades if t.trade_id in mixed_res.flagged_trade_ids
    }
    m_tp = len(m_flagged_oids & m_gt_oids)
    m_fp = len(m_flagged_oids - m_gt_oids)
    m_fn = len(m_gt_oids - m_flagged_oids)
    m_prec = m_tp / (m_tp + m_fp) if (m_tp + m_fp) > 0 else 0.0
    m_rec = m_tp / (m_tp + m_fn) if (m_tp + m_fn) > 0 else 0.0

    print("\n--- mixed.csv ---")
    print(f"Precision: {m_prec:.3f}")
    print(f"Recall: {m_rec:.3f}")
    print(f"Estimated Cost: ₹{mixed_res.estimated_cost_inr:,.2f}")
    print(f"Injected Loss:  ₹{mixed_gt['injected_loss_inr']:,.2f}")

    # 4. Report other single_* datasets
    print("\n--- Other Single Habit Datasets ---")
    for ds_name in [
        "single_revenge_trading",
        "single_overtrading",
        "single_oversizing",
        "single_averaging_down",
    ]:
        ds_trades = pair_orders(parse_orders(Path(f"data/datasets/{ds_name}.csv")).orders).trades
        ds_res = detector.detect(ds_trades)
        status_str = f"FIRED (₹{ds_res.estimated_cost_inr:,.2f})" if ds_res else "None"
        print(f"{ds_name}: {status_str}")


def test_holding_losers_multi_seed_robustness() -> None:
    """Verify multi-seed robustness across 30 clean months and 30 planted months."""
    detector = HoldingLosersDetector()

    # 30 clean months: assert detector fires on at most 1 of the 30
    clean_fired = 0
    for s in range(500, 530):
        csv_txt, _ = generate_dataset_in_memory(seed=s)
        orders = parse_orders(csv_txt).orders
        trades = pair_orders(orders).trades
        if detector.detect(trades) is not None:
            clean_fired += 1

    print(f"\nMulti-seed clean months fired: {clean_fired}/30")
    assert clean_fired <= 1, f"Clean months fired {clean_fired}/30 times (> 1)"

    # 30 planted months: assert fraction detected >= 0.8 (at least 24 of 30)
    planted_fired = 0
    for s in range(600, 630):
        csv_txt, _ = generate_dataset_in_memory(
            seed=s, habits_config={"holding_losers": "medium"}
        )
        orders = parse_orders(csv_txt).orders
        trades = pair_orders(orders).trades
        if detector.detect(trades) is not None:
            planted_fired += 1

    detection_rate = planted_fired / 30.0
    print(f"Multi-seed planted months detected: {planted_fired}/30 ({detection_rate:.1%})")
    assert detection_rate >= 0.8, f"Detection rate {detection_rate:.1%} < 80% ({planted_fired}/30)"
