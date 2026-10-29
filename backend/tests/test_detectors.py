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
from app.detectors.revenge_trading import (
    RevengeTradingDetector,
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


# =====================================================================
# SECTION 2: RevengeTradingDetector Tests
# =====================================================================


def _make_rt_trade(
    trade_id: str,
    entry_time: datetime,
    exit_time: datetime,
    quantity: int,
    gross_pnl: float,
    entry_order_id: str,
    exit_order_id: str,
    is_add_on: bool = False,
    is_partial_exit: bool = False,
) -> Trade:
    """Helper to create Trade objects for revenge trading tests."""
    return Trade(
        trade_id=trade_id,
        symbol="NIFTY24OCT25000CE",
        instrument_type="CE",
        strike=25000.0,
        expiry=date(2024, 10, 31),
        direction="LONG",
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=100.0,
        exit_price=100.0 + (gross_pnl / quantity) if quantity > 0 else 100.0,
        quantity=quantity,
        lot_size=25,
        hold_minutes=(exit_time - entry_time).total_seconds() / 60.0,
        gross_pnl=gross_pnl,
        entry_order_id=entry_order_id,
        exit_order_id=exit_order_id,
        is_partial_exit=is_partial_exit,
        is_add_on=is_add_on,
        trading_date=entry_time.date(),
    )


def test_revenge_trading_fires_on_constructed_case() -> None:
    """Verify detector fires on constructed case with exact hand-calculated metrics."""
    base = datetime(2024, 10, 1, 9, 30, tzinfo=IST)

    # Pair 1: Prior loss (qty 50, pnl -2000), Revenge trade (qty 100, gap 10m, pnl -4000)
    t1 = _make_rt_trade(
        "T1", base, base + timedelta(minutes=10), 50, -2000.0, "E1", "X1"
    )
    t2 = _make_rt_trade(
        "T2", base + timedelta(minutes=20), base + timedelta(minutes=30), 100, -4000.0, "E2", "X2"
    )

    # Pair 2: Prior loss (qty 50, pnl -1500), Revenge trade (qty 75, gap 5m, pnl +1000 - winner!)
    base2 = datetime(2024, 10, 1, 10, 30, tzinfo=IST)
    t3 = _make_rt_trade(
        "T3", base2, base2 + timedelta(minutes=10), 50, -1500.0, "E3", "X3"
    )
    t4 = _make_rt_trade(
        "T4", base2 + timedelta(minutes=15), base2 + timedelta(minutes=25), 75, 1000.0, "E4", "X4"
    )

    # Pair 3: Prior loss (qty 100, pnl -3000), Revenge trade (qty 200, gap 12m, pnl -5000)
    base3 = datetime(2024, 10, 1, 11, 30, tzinfo=IST)
    t5 = _make_rt_trade(
        "T5", base3, base3 + timedelta(minutes=10), 100, -3000.0, "E5", "X5"
    )
    t6 = _make_rt_trade(
        "T6", base3 + timedelta(minutes=22), base3 + timedelta(minutes=35), 200, -5000.0, "E6", "X6"
    )

    trades = [t1, t2, t3, t4, t5, t6]
    detector = RevengeTradingDetector()
    res = detector.detect(trades)

    assert res is not None
    assert res.key == "revenge_trading"
    assert res.name == "Re-entering fast after a loss with a bigger size"
    assert res.flagged_trade_ids == ["T2", "T4", "T6"]

    # Net loss on revenge trades: -(-4000 + 1000 + -5000) = 8000.0
    assert res.estimated_cost_inr == 8000.0
    assert res.confidence == 0.38  # min(1.0, 3 / 8.0) = 0.375 -> 0.38

    # Metrics verification
    assert res.metrics["eligible_entries"] == 3
    assert res.metrics["flagged_entries"] == 3
    # avg_size_multiple: (100/50 + 75/50 + 200/100) / 3 = (2.0 + 1.5 + 2.0) / 3 = 1.83
    assert res.metrics["avg_size_multiple"] == 1.83
    # avg_gap_minutes: (10.0 + 5.0 + 12.0) / 3 = 9.0
    assert res.metrics["avg_gap_minutes"] == 9.0
    assert res.metrics["flagged_net_pnl_inr"] == -8000.0
    # revenge_win_rate: 1 profitable entry out of 3 = 0.33
    assert res.metrics["revenge_win_rate"] == 0.33
    assert len(res.formula_note) > 0


def test_revenge_trading_negative_guards() -> None:
    """Verify None when gap > 15m, size < 1.5x, prior was a win, or flagged < 3."""
    detector = RevengeTradingDetector()
    base = datetime(2024, 10, 1, 9, 30, tzinfo=IST)

    # 1. Gap is 16 minutes (> 15m window) -> only 2 flagged -> returns None
    t1 = _make_rt_trade("T1", base, base + timedelta(minutes=10), 50, -2000.0, "E1", "X1")
    t2 = _make_rt_trade(
        "T2", base + timedelta(minutes=26), base + timedelta(minutes=35), 100, -4000.0, "E2", "X2"
    )
    t3 = _make_rt_trade(
        "T3", base + timedelta(minutes=40), base + timedelta(minutes=50), 50, -1000.0, "E3", "X3"
    )
    t4 = _make_rt_trade(
        "T4", base + timedelta(minutes=55), base + timedelta(minutes=65), 100, -3000.0, "E4", "X4"
    )
    assert detector.detect([t1, t2, t3, t4]) is None

    # 2. Size multiple is 1.48x (< 1.5x)
    t2_small = _make_rt_trade(
        "T2", base + timedelta(minutes=20), base + timedelta(minutes=30), 74, -4000.0, "E2", "X2"
    )
    assert detector.detect([t1, t2_small, t3, t4]) is None

    # 3. Prior trade was a win (pnl = +1000)
    t1_win = _make_rt_trade("T1", base, base + timedelta(minutes=10), 50, 1000.0, "E1", "X1")
    t2_valid = _make_rt_trade(
        "T2", base + timedelta(minutes=20), base + timedelta(minutes=30), 100, -4000.0, "E2", "X2"
    )
    assert detector.detect([t1_win, t2_valid, t3, t4]) is None

    # 4. Only 2 flagged trades total (< 3 MIN_FLAGGED)
    assert detector.detect([t1, t2_valid, t3, t4]) is None


def test_revenge_trading_boundaries() -> None:
    """Verify boundary conditions: exactly 15 min gap and exactly 1.5x size count as flagged."""
    detector = RevengeTradingDetector()
    trades = []
    for i in range(3):
        base = datetime(2024, 10, 1, 9 + i, 0, tzinfo=IST)
        # Prior loss exit at :10
        t_prev = _make_rt_trade(
            f"P{i}", base, base + timedelta(minutes=10), 50, -1000.0, f"EP{i}", f"XP{i}"
        )
        # Entry at :25 -> exactly 15.0 minutes gap. Size = 75 -> exactly 1.5x 50.
        t_curr = _make_rt_trade(
            f"R{i}", base + timedelta(minutes=25), base + timedelta(minutes=35), 75, -2000.0,
            f"ER{i}", f"XR{i}"
        )
        trades.extend([t_prev, t_curr])

    res = detector.detect(trades)
    assert res is not None
    assert res.metrics["flagged_entries"] == 3
    assert res.metrics["avg_gap_minutes"] == 15.0
    assert res.metrics["avg_size_multiple"] == 1.5


def test_revenge_trading_multi_slice_closing_event() -> None:
    """Verify closing events across multiple slices are aggregated for qty and P&L."""
    detector = RevengeTradingDetector()
    base = datetime(2024, 10, 1, 9, 30, tzinfo=IST)

    # Closing event with 2 slices sharing exit_order_id "X1"
    # Slice 1: qty 30, pnl -600.0
    t1a = _make_rt_trade(
        "T1A", base, base + timedelta(minutes=10), 30, -600.0, "E1A", "X1", is_partial_exit=True
    )
    # Slice 2: qty 20, pnl -400.0
    t1b = _make_rt_trade(
        "T1B", base, base + timedelta(minutes=10), 20, -400.0, "E1B", "X1", is_partial_exit=True
    )
    # Aggregated closing event has qty = 50, pnl = -1000.0
    # Next trade: qty 75 (exactly 1.5x 50), entry 10m later -> flagged!
    t2 = _make_rt_trade(
        "T2", base + timedelta(minutes=20), base + timedelta(minutes=30), 75, -2000.0, "E2", "X2"
    )

    # 2 more valid flagged pairs to reach MIN_FLAGGED (3)
    t3 = _make_rt_trade(
        "T3", base + timedelta(minutes=40), base + timedelta(minutes=50), 50, -1000.0, "E3", "X3"
    )
    t4 = _make_rt_trade(
        "T4", base + timedelta(minutes=55), base + timedelta(minutes=65), 100, -2000.0, "E4", "X4"
    )
    t5 = _make_rt_trade(
        "T5", base + timedelta(minutes=70), base + timedelta(minutes=80), 50, -1000.0, "E5", "X5"
    )
    t6 = _make_rt_trade(
        "T6", base + timedelta(minutes=85), base + timedelta(minutes=95), 100, -2000.0, "E6", "X6"
    )

    trades = [t1a, t1b, t2, t3, t4, t5, t6]
    res = detector.detect(trades)
    assert res is not None
    assert res.metrics["flagged_entries"] == 3
    # Check avg_size_multiple: (75/50 + 100/50 + 100/50) / 3 = (1.5 + 2.0 + 2.0) / 3 = 1.83
    assert res.metrics["avg_size_multiple"] == 1.83


def test_revenge_trading_addon_entries_skipped() -> None:
    """Verify entries marked as add-ons (is_add_on = True) are skipped."""
    detector = RevengeTradingDetector()
    base = datetime(2024, 10, 1, 9, 30, tzinfo=IST)

    # Prior loss
    t1 = _make_rt_trade("T1", base, base + timedelta(minutes=10), 50, -1000.0, "E1", "X1")
    # Add-on entry within 10 min and size 2x -> skipped because is_add_on = True
    t2_addon = _make_rt_trade(
        "T2", base + timedelta(minutes=20), base + timedelta(minutes=30), 100, -2000.0, "E2", "X2",
        is_add_on=True
    )
    # Only 2 other valid flagged trades
    t3 = _make_rt_trade(
        "T3", base + timedelta(minutes=40), base + timedelta(minutes=50), 50, -1000.0, "E3", "X3"
    )
    t4 = _make_rt_trade(
        "T4", base + timedelta(minutes=55), base + timedelta(minutes=65), 100, -2000.0, "E4", "X4"
    )

    assert detector.detect([t1, t2_addon, t3, t4]) is None


def test_revenge_trading_no_prior_event_ignored() -> None:
    """Verify entry with no prior closing event is safely ignored."""
    detector = RevengeTradingDetector()
    base = datetime(2024, 10, 1, 9, 30, tzinfo=IST)

    # First entry has no prior event
    t1 = _make_rt_trade("T1", base, base + timedelta(minutes=10), 100, -2000.0, "E1", "X1")
    assert detector.detect([t1]) is None


def test_revenge_trading_net_cost_zero_or_negative_returns_none() -> None:
    """Verify detector returns None when net loss on revenge trades <= 0."""
    detector = RevengeTradingDetector()
    base = datetime(2024, 10, 1, 9, 30, tzinfo=IST)

    # 3 flagged entries that all end up profitable (net P&L > 0)
    trades = []
    for i in range(3):
        b = base + timedelta(hours=i)
        t_prev = _make_rt_trade(
            f"P{i}", b, b + timedelta(minutes=10), 50, -1000.0, f"EP{i}", f"XP{i}"
        )
        t_curr = _make_rt_trade(
            f"R{i}", b + timedelta(minutes=15), b + timedelta(minutes=25), 100, 3000.0,
            f"ER{i}", f"XR{i}"
        )
        trades.extend([t_prev, t_curr])

    # Net PnL of revenge trades is +9000 -> estimated cost is 0 -> returns None
    assert detector.detect(trades) is None


def test_revenge_trading_determinism() -> None:
    """Verify detector output is completely deterministic."""
    detector = RevengeTradingDetector()
    base = datetime(2024, 10, 1, 9, 30, tzinfo=IST)
    trades = []
    for i in range(3):
        b = base + timedelta(hours=i)
        trades.append(_make_rt_trade(
            f"P{i}", b, b + timedelta(minutes=10), 50, -1000.0, f"EP{i}", f"XP{i}"
        ))
        trades.append(_make_rt_trade(
            f"R{i}", b + timedelta(minutes=15), b + timedelta(minutes=25), 100, -2000.0,
            f"ER{i}", f"XR{i}"
        ))

    res1 = detector.detect(trades)
    res2 = detector.detect(trades)
    assert res1 is not None and res2 is not None
    assert res1.estimated_cost_inr == res2.estimated_cost_inr
    assert res1.flagged_trade_ids == res2.flagged_trade_ids
    assert res1.metrics == res2.metrics
    assert res1.formula_note == res2.formula_note


def test_revenge_trading_benchmark_datasets() -> None:
    """Test RevengeTradingDetector on benchmark datasets."""
    detector = RevengeTradingDetector()

    # 1. clean.csv: must return None
    clean_trades = pair_orders(parse_orders(Path("data/datasets/clean.csv")).orders).trades
    assert detector.detect(clean_trades) is None, "revenge_trading falsely fired on clean.csv"

    # 2. single_revenge_trading.csv
    single_trades = pair_orders(
        parse_orders(Path("data/datasets/single_revenge_trading.csv")).orders
    ).trades
    with open("data/ground_truth/single_revenge_trading.json") as f:
        gt_data = json.load(f)
    gt_revenge = gt_data["habits"]["revenge_trading"]

    res = detector.detect(single_trades)
    assert res is not None, "revenge_trading failed to fire on single_revenge_trading.csv"

    # Map flagged trade IDs to entry_order_ids
    detected_oids = set(
        t.entry_order_id for t in single_trades if t.trade_id in res.flagged_trade_ids
    )
    true_oids = set(gt_revenge["entry_order_ids"])

    tp = len(detected_oids & true_oids)
    precision = tp / len(detected_oids) if detected_oids else 0.0
    recall = tp / len(true_oids) if true_oids else 0.0
    injected_loss = gt_revenge["injected_loss_inr"]

    print("\n--- single_revenge_trading.csv Evaluation ---")
    print(f"Precision: {precision:.3f}")
    print(f"Recall:    {recall:.3f}")
    print(f"Estimated Cost: ₹{res.estimated_cost_inr:,.2f}")
    print(f"Injected Loss:  ₹{injected_loss:,.2f}")
    print(
        "Explanation of injected_loss_inr: The generator forces planted revenge trades "
        "to suffer a 20-50% loss upon re-entry, summing the absolute rupee loss of every "
        "planted revenge trade as injected_loss_inr. The detector measures net rupee loss "
        "on all flagged revenge trades (winners offset losers). In the planted dataset, all "
        "planted revenge trades took losses, so the comparison is like-for-like."
    )

    assert precision >= 0.8, f"Precision {precision:.3f} < 0.8"
    assert recall >= 0.6, f"Recall {recall:.3f} < 0.6"
    assert (
        0.5 * injected_loss <= res.estimated_cost_inr <= 2.0 * injected_loss
    ), f"Cost ₹{res.estimated_cost_inr} out of bounds for injected ₹{injected_loss}"

    # 3. mixed.csv
    mixed_trades = pair_orders(parse_orders(Path("data/datasets/mixed.csv")).orders).trades
    with open("data/ground_truth/mixed.json") as f:
        mixed_gt = json.load(f)["habits"]["revenge_trading"]

    mixed_res = detector.detect(mixed_trades)
    assert mixed_res is not None, "revenge_trading failed to fire on mixed.csv"

    m_detected_oids = set(
        t.entry_order_id for t in mixed_trades if t.trade_id in mixed_res.flagged_trade_ids
    )
    m_true_oids = set(mixed_gt["entry_order_ids"])
    m_tp = len(m_detected_oids & m_true_oids)
    m_prec = m_tp / len(m_detected_oids) if m_detected_oids else 0.0
    m_rec = m_tp / len(m_true_oids) if m_true_oids else 0.0

    # Overlap with holding_losers flags on mixed.csv
    hl_res = HoldingLosersDetector().detect(mixed_trades)
    hl_flagged = set(hl_res.flagged_trade_ids) if hl_res else set()
    overlap_count = len(set(mixed_res.flagged_trade_ids) & hl_flagged)

    print("\n--- mixed.csv Evaluation ---")
    print(f"Precision: {m_prec:.3f}")
    print(f"Recall:    {m_rec:.3f}")
    print(f"Estimated Cost: ₹{mixed_res.estimated_cost_inr:,.2f}")
    print(f"Injected Loss:  ₹{mixed_gt['injected_loss_inr']:,.2f}")
    print(f"Flagged trade ID overlap with holding_losers: {overlap_count} trades")

    # 4. Report other single_* datasets
    print("\n--- Other Single Habit Datasets ---")
    for ds_name in [
        "single_holding_losers",
        "single_overtrading",
        "single_oversizing",
        "single_averaging_down",
    ]:
        ds_trades = pair_orders(parse_orders(Path(f"data/datasets/{ds_name}.csv")).orders).trades
        ds_res = detector.detect(ds_trades)
        status_str = f"FIRED (₹{ds_res.estimated_cost_inr:,.2f})" if ds_res else "None"
        print(f"{ds_name}: {status_str}")


def test_revenge_trading_multi_seed_robustness() -> None:
    """Verify multi-seed robustness across 30 clean months and 30 planted months."""
    detector = RevengeTradingDetector()

    # 30 clean months: assert detector fires on at most 1 of 30
    clean_fired = 0
    for s in range(700, 730):
        csv_txt, _ = generate_dataset_in_memory(seed=s)
        orders = parse_orders(csv_txt).orders
        trades = pair_orders(orders).trades
        if detector.detect(trades) is not None:
            clean_fired += 1

    clean_fraction = clean_fired / 30.0
    print(f"\nMulti-seed clean months fired: {clean_fired}/30 ({clean_fraction:.1%})")
    assert clean_fired <= 1, f"Clean months fired {clean_fired}/30 times (> 1)"

    # 30 planted months: assert fraction detected >= 0.8
    planted_fired = 0
    for s in range(800, 830):
        csv_txt, _ = generate_dataset_in_memory(
            seed=s, habits_config={"revenge_trading": "medium"}
        )
        orders = parse_orders(csv_txt).orders
        trades = pair_orders(orders).trades
        if detector.detect(trades) is not None:
            planted_fired += 1

    detection_rate = planted_fired / 30.0
    print(f"Multi-seed planted months detected: {planted_fired}/30 ({detection_rate:.1%})")
    assert detection_rate >= 0.8, f"Detection rate {detection_rate:.1%} < 80% ({planted_fired}/30)"

