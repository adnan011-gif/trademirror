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
from app.detectors.overtrading import (
    OvertradingDetector,
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


# =====================================================================
# SECTION 3: OvertradingDetector Tests
# =====================================================================


def _make_ot_trade(
    trade_id: str,
    trading_date: date,
    entry_time: datetime,
    gross_pnl: float,
    entry_order_id: str,
    exit_order_id: str,
    quantity: int = 75,
    is_add_on: bool = False,
    is_partial_exit: bool = False,
) -> Trade:
    """Helper to create Trade objects for overtrading detector tests."""
    return Trade(
        trade_id=trade_id,
        symbol="NIFTY24OCT25000CE",
        instrument_type="CE",
        strike=25000.0,
        expiry=date(2024, 10, 31),
        direction="LONG",
        entry_time=entry_time,
        exit_time=entry_time + timedelta(minutes=15),
        entry_price=100.0,
        exit_price=100.0 + (gross_pnl / quantity) if quantity > 0 else 100.0,
        quantity=quantity,
        lot_size=75,
        hold_minutes=15.0,
        gross_pnl=gross_pnl,
        entry_order_id=entry_order_id,
        exit_order_id=exit_order_id,
        is_partial_exit=is_partial_exit,
        is_add_on=is_add_on,
        trading_date=trading_date,
    )


def test_overtrading_fires_on_constructed_case() -> None:
    """Verify detector fires on constructed case with exact hand-calculated metrics."""
    trades: list[Trade] = []

    # Days 1 to 8: Baseline days, 2 trades each (total 16 trades)
    for day_idx in range(1, 9):
        d = date(2024, 10, day_idx)
        t1 = _make_ot_trade(
            f"B{day_idx}_1", d, datetime(2024, 10, day_idx, 9, 30, tzinfo=IST),
            1000.0, f"EB{day_idx}_1", f"XB{day_idx}_1"
        )
        t2 = _make_ot_trade(
            f"B{day_idx}_2", d, datetime(2024, 10, day_idx, 10, 30, tzinfo=IST),
            -500.0, f"EB{day_idx}_2", f"XB{day_idx}_2"
        )
        trades.extend([t1, t2])

    # Day 9: Spike day 1 with 6 trades (median=2.0, 6 > 2.0*2=4)
    # Trades 1-2: normal (+1000 each), Trades 3-6: excess (-1000 each -> excess loss 4000)
    d9 = date(2024, 10, 9)
    for i in range(1, 7):
        pnl = 1000.0 if i <= 2 else -1000.0
        trades.append(
            _make_ot_trade(
                f"S9_{i}", d9, datetime(2024, 10, 9, 9 + i, 0, tzinfo=IST),
                pnl, f"ES9_{i}", f"XS9_{i}"
            )
        )

    # Day 10: Spike day 2 with 5 trades (5 > 4)
    # Trades 1-2: normal (+500 each), Trades 3-5: excess (-1000 each -> excess loss 3000)
    d10 = date(2024, 10, 10)
    for i in range(1, 6):
        pnl = 500.0 if i <= 2 else -1000.0
        trades.append(
            _make_ot_trade(
                f"S10_{i}", d10, datetime(2024, 10, 10, 9 + i, 0, tzinfo=IST),
                pnl, f"ES10_{i}", f"XS10_{i}"
            )
        )

    detector = OvertradingDetector()
    res = detector.detect(trades)

    assert res is not None
    assert res.key == "overtrading"
    assert res.name == "Taking far more trades than usual on some days"

    # Excess trades are S9_3, S9_4, S9_5, S9_6, S10_3, S10_4, S10_5
    expected_flagged = ["S10_3", "S10_4", "S10_5", "S9_3", "S9_4", "S9_5", "S9_6"]
    assert res.flagged_trade_ids == sorted(expected_flagged)

    # Hand-computed cost: 4 * 1000 + 3 * 1000 = 7000.0
    assert res.estimated_cost_inr == 7000.0
    assert res.confidence == 0.5  # min(1.0, 2 / 4.0) = 0.5

    # Metrics
    assert res.metrics["n_days"] == 10
    assert res.metrics["median_daily_trades"] == 2.0
    assert res.metrics["spike_days"] == ["2024-10-09", "2024-10-10"]
    assert res.metrics["spike_day_count"] == 2
    assert res.metrics["excess_trades"] == 7
    assert res.metrics["excess_net_pnl_inr"] == -7000.0
    assert res.metrics["excess_win_rate"] == 0.0
    assert res.metrics["avg_trades_on_spike_days"] == 5.5
    assert len(res.formula_note) > 0


def test_overtrading_spike_multiple_boundary() -> None:
    """Verify exactly 2.0x median is NOT a spike; 2.0x + 1 trade is a spike."""
    detector = OvertradingDetector()

    # 10 days where median = 3
    # 8 days with 3 trades
    trades: list[Trade] = []
    for day_idx in range(1, 9):
        d = date(2024, 10, day_idx)
        for i in range(3):
            trades.append(
                _make_ot_trade(
                    f"B{day_idx}_{i}", d,
                    datetime(2024, 10, day_idx, 9 + i, 0, tzinfo=IST),
                    100.0, f"EB{day_idx}_{i}", f"XB{day_idx}_{i}"
                )
            )

    # Day 9: exactly 2.0x median = 2.0 * 3 = 6 trades (NOT a spike day because strictly >)
    d9 = date(2024, 10, 9)
    for i in range(6):
        trades.append(
            _make_ot_trade(
                f"D9_{i}", d9,
                datetime(2024, 10, 9, 9 + i, 0, tzinfo=IST),
                -500.0, f"ED9_{i}", f"XD9_{i}"
            )
        )

    # Day 10: 7 trades = 2.0x + 1 (IS a spike day)
    d10 = date(2024, 10, 10)
    for i in range(7):
        trades.append(
            _make_ot_trade(
                f"D10_{i}", d10,
                datetime(2024, 10, 10, 9 + i, 0, tzinfo=IST),
                -500.0, f"ED10_{i}", f"XD10_{i}"
            )
        )

    # Day 9 has 6 trades, which is not > 6.0 (not a spike day).
    # Only Day 10 is a spike day (< 2 MIN_SPIKE_DAYS).
    assert detector.detect(trades) is None

    # Now add 1 trade to Day 9 making it 7 trades (> 6.0) -> now 2 spike days!
    trades.append(
        _make_ot_trade(
            "D9_6", d9,
            datetime(2024, 10, 9, 15, 0, tzinfo=IST),
            -500.0, "ED9_6", "XD9_6"
        )
    )
    res = detector.detect(trades)
    assert res is not None
    assert res.metrics["spike_day_count"] == 2
    assert res.metrics["spike_days"] == ["2024-10-09", "2024-10-10"]


def test_overtrading_minimum_sample_guards() -> None:
    """Verify None when distinct days < 10 or spike days < 2."""
    detector = OvertradingDetector()

    # 1. 9 days total (< 10 MIN_DAYS) even with multiple spikes
    trades_9days: list[Trade] = []
    for day_idx in range(1, 10):
        d = date(2024, 10, day_idx)
        count = 6 if day_idx in [8, 9] else 2
        for i in range(count):
            trades_9days.append(
                _make_ot_trade(
                    f"T_{day_idx}_{i}", d,
                    datetime(2024, 10, day_idx, 9 + i, 0, tzinfo=IST),
                    -500.0, f"E_{day_idx}_{i}", f"X_{day_idx}_{i}"
                )
            )
    assert detector.detect(trades_9days) is None

    # 2. 10 days total, but only 1 spike day
    trades_1spike: list[Trade] = []
    for day_idx in range(1, 11):
        d = date(2024, 10, day_idx)
        count = 6 if day_idx == 10 else 2
        for i in range(count):
            trades_1spike.append(
                _make_ot_trade(
                    f"T_{day_idx}_{i}", d,
                    datetime(2024, 10, day_idx, 9 + i, 0, tzinfo=IST),
                    -500.0, f"E_{day_idx}_{i}", f"X_{day_idx}_{i}"
                )
            )
    assert detector.detect(trades_1spike) is None


def test_overtrading_even_days_and_ceil_keep_n() -> None:
    """Verify median with even number of days and ceil on fractional median setting keep_n."""
    detector = OvertradingDetector()

    # 10 days with counts: [2, 2, 2, 2, 2, 3, 3, 3, 8, 8]
    # Median is (2 + 3) / 2 = 2.5. Spike threshold = 2.0 * 2.5 = 5.0. Both 8s are spikes.
    # keep_n = ceil(2.5) = 3. Excess per spike day = 8 - 3 = 5. Total excess = 10.
    counts = [2, 2, 2, 2, 2, 3, 3, 3, 8, 8]
    trades: list[Trade] = []
    for day_idx, cnt in enumerate(counts, start=1):
        d = date(2024, 10, day_idx)
        for i in range(cnt):
            trades.append(
                _make_ot_trade(
                    f"T_{day_idx}_{i}", d,
                    datetime(2024, 10, day_idx, 9 + (i % 6), i * 5, tzinfo=IST),
                    -500.0, f"E_{day_idx}_{i}", f"X_{day_idx}_{i}"
                )
            )

    res = detector.detect(trades)
    assert res is not None
    assert res.metrics["median_daily_trades"] == 2.5
    assert res.metrics["excess_trades"] == 10  # 2 spike days * 5 excess trades each
    assert res.metrics["spike_day_count"] == 2


def test_overtrading_excess_selection_chronological() -> None:
    """Verify excess selection orders by (entry_time, entry_order_id) keeping earliest as normal."""
    detector = OvertradingDetector()

    # 10 days: 8 days with 1 trade, 2 spike days with 3 trades (median=1, 3 > 2.0*1=2)
    # keep_n = 1. Earliest trade on spike day is normal, 2 later trades are excess.
    trades: list[Trade] = []
    for day_idx in range(1, 9):
        d = date(2024, 10, day_idx)
        trades.append(
            _make_ot_trade(
                f"N_{day_idx}", d,
                datetime(2024, 10, day_idx, 9, 30, tzinfo=IST),
                100.0, f"EN_{day_idx}", f"XN_{day_idx}"
            )
        )

    # Spike day 9: entries at 09:30 (normal), 11:00 (excess), 14:00 (excess)
    d9 = date(2024, 10, 9)
    trades.append(
        _make_ot_trade(
            "D9_EARLY", d9, datetime(2024, 10, 9, 9, 30, tzinfo=IST), 100.0, "E9_1", "X9_1"
        )
    )
    trades.append(
        _make_ot_trade(
            "D9_MID", d9, datetime(2024, 10, 9, 11, 0, tzinfo=IST), -500.0, "E9_2", "X9_2"
        )
    )
    trades.append(
        _make_ot_trade(
            "D9_LATE", d9, datetime(2024, 10, 9, 14, 0, tzinfo=IST), -500.0, "E9_3", "X9_3"
        )
    )

    # Spike day 10: entries at 09:30 (normal), 11:00 (excess), 14:00 (excess)
    d10 = date(2024, 10, 10)
    trades.append(
        _make_ot_trade(
            "D10_EARLY", d10, datetime(2024, 10, 10, 9, 30, tzinfo=IST), 100.0, "E10_1", "X10_1"
        )
    )
    trades.append(
        _make_ot_trade(
            "D10_MID", d10, datetime(2024, 10, 10, 11, 0, tzinfo=IST), -500.0, "E10_2", "X10_2"
        )
    )
    trades.append(
        _make_ot_trade(
            "D10_LATE", d10, datetime(2024, 10, 10, 14, 0, tzinfo=IST), -500.0, "E10_3", "X10_3"
        )
    )

    res = detector.detect(trades)
    assert res is not None
    assert "D9_EARLY" not in res.flagged_trade_ids
    assert "D10_EARLY" not in res.flagged_trade_ids
    assert res.flagged_trade_ids == ["D10_LATE", "D10_MID", "D9_LATE", "D9_MID"]


def test_overtrading_multi_slice_entry_counts_as_one() -> None:
    """Verify multi-slice entry event (same entry_order_id) counts as one trade taken."""
    detector = OvertradingDetector()

    trades: list[Trade] = []
    for day_idx in range(1, 9):
        d = date(2024, 10, day_idx)
        trades.append(
            _make_ot_trade(
                f"N_{day_idx}", d,
                datetime(2024, 10, day_idx, 9, 30, tzinfo=IST),
                100.0, f"EN_{day_idx}", f"XN_{day_idx}"
            )
        )

    # Day 9: 1 multi-slice entry (3 slices) + 1 regular entry = 2 entry events (not 4)
    # Median is 1. If multi-slice counted as 3, day 9 would have 4 entries > 2 (spike).
    # Since it counts as 2, 2 > 2.0*1=2 is False, so Day 9 is NOT a spike!
    d9 = date(2024, 10, 9)
    for slice_idx in range(1, 4):
        trades.append(
            _make_ot_trade(
                f"S9_SLICE_{slice_idx}", d9,
                datetime(2024, 10, 9, 9, 30, tzinfo=IST),
                -200.0, "E_MULTI", f"X_MULTI_{slice_idx}", is_partial_exit=True
            )
        )
    trades.append(
        _make_ot_trade(
            "S9_OTHER", d9, datetime(2024, 10, 9, 11, 0, tzinfo=IST), -200.0, "E_OTHER", "X_OTHER"
        )
    )

    # Day 10: 1 entry
    d10 = date(2024, 10, 10)
    trades.append(
        _make_ot_trade(
            "D10_1", d10, datetime(2024, 10, 10, 9, 30, tzinfo=IST), -200.0, "ED10_1", "XD10_1"
        )
    )

    # Should return None because Day 9 is not a spike (2 is not > 2.0)
    assert detector.detect(trades) is None


def test_overtrading_addon_entries_not_counted() -> None:
    """Verify add-on entries (is_add_on = True) are not counted toward daily entries."""
    detector = OvertradingDetector()

    trades: list[Trade] = []
    for day_idx in range(1, 11):
        d = date(2024, 10, day_idx)
        # 1 normal entry
        trades.append(
            _make_ot_trade(
                f"N_{day_idx}", d,
                datetime(2024, 10, day_idx, 9, 30, tzinfo=IST),
                100.0, f"EN_{day_idx}", f"XN_{day_idx}"
            )
        )
        # 4 add-on entries (should be skipped!)
        for i in range(4):
            trades.append(
                _make_ot_trade(
                    f"ADD_{day_idx}_{i}", d,
                    datetime(2024, 10, day_idx, 10 + i, 0, tzinfo=IST),
                    -200.0, f"EADD_{day_idx}_{i}", f"XADD_{day_idx}_{i}", is_add_on=True
                )
            )

    # Every day has exactly 1 valid entry event. Spike count is 0 -> returns None
    assert detector.detect(trades) is None


def test_overtrading_net_positive_excess_returns_none() -> None:
    """Verify detector returns None when net P&L on excess trades is positive."""
    detector = OvertradingDetector()

    trades: list[Trade] = []
    for day_idx in range(1, 9):
        d = date(2024, 10, day_idx)
        trades.append(
            _make_ot_trade(
                f"N_{day_idx}", d,
                datetime(2024, 10, day_idx, 9, 30, tzinfo=IST),
                -100.0, f"EN_{day_idx}", f"XN_{day_idx}"
            )
        )

    # 2 spike days where excess trades make money (+5000 each)
    for day_idx in [9, 10]:
        d = date(2024, 10, day_idx)
        trades.append(
            _make_ot_trade(
                f"S{day_idx}_1", d, datetime(2024, 10, day_idx, 9, 30, tzinfo=IST),
                -100.0, f"E{day_idx}_1", f"X{day_idx}_1"
            )
        )
        trades.append(
            _make_ot_trade(
                f"S{day_idx}_2", d, datetime(2024, 10, day_idx, 11, 0, tzinfo=IST),
                3000.0, f"E{day_idx}_2", f"X{day_idx}_2"
            )
        )
        trades.append(
            _make_ot_trade(
                f"S{day_idx}_3", d, datetime(2024, 10, day_idx, 14, 0, tzinfo=IST),
                2000.0, f"E{day_idx}_3", f"X{day_idx}_3"
            )
        )

    # Excess net P&L is +10000 -> estimated cost is 0 -> returns None
    assert detector.detect(trades) is None


def test_overtrading_determinism() -> None:
    """Verify detector produces deterministic output on repeated invocations."""
    detector = OvertradingDetector()
    trades: list[Trade] = []
    for day_idx in range(1, 9):
        d = date(2024, 10, day_idx)
        trades.extend([
            _make_ot_trade(
                f"B{day_idx}_1", d, datetime(2024, 10, day_idx, 9, 30, tzinfo=IST),
                1000.0, f"EB{day_idx}_1", f"XB{day_idx}_1"
            ),
            _make_ot_trade(
                f"B{day_idx}_2", d, datetime(2024, 10, day_idx, 10, 30, tzinfo=IST),
                -500.0, f"EB{day_idx}_2", f"XB{day_idx}_2"
            ),
        ])
    for day_idx in [9, 10]:
        d = date(2024, 10, day_idx)
        for i in range(1, 6):
            trades.append(
                _make_ot_trade(
                    f"S{day_idx}_{i}", d,
                    datetime(2024, 10, day_idx, 9 + i, 0, tzinfo=IST),
                    -1000.0, f"ES{day_idx}_{i}", f"XS{day_idx}_{i}"
                )
            )

    res1 = detector.detect(trades)
    res2 = detector.detect(trades)
    assert res1 is not None and res2 is not None
    assert res1.estimated_cost_inr == res2.estimated_cost_inr
    assert res1.flagged_trade_ids == res2.flagged_trade_ids
    assert res1.metrics == res2.metrics
    assert res1.formula_note == res2.formula_note


def test_overtrading_benchmark_datasets() -> None:
    """Test OvertradingDetector on benchmark datasets."""
    detector = OvertradingDetector()

    # 1. clean.csv: must return None
    clean_trades = pair_orders(parse_orders(Path("data/datasets/clean.csv")).orders).trades
    assert detector.detect(clean_trades) is None, "overtrading falsely fired on clean.csv"

    # 2. single_overtrading.csv
    single_trades = pair_orders(
        parse_orders(Path("data/datasets/single_overtrading.csv")).orders
    ).trades
    with open("data/ground_truth/single_overtrading.json") as f:
        gt_data = json.load(f)
    gt_ot = gt_data["habits"]["overtrading"]

    res = detector.detect(single_trades)
    assert res is not None, "overtrading failed to fire on single_overtrading.csv"

    # a) Day level evaluation
    gt_entry_oids = set(gt_ot["entry_order_ids"])
    gt_planted_days = set(
        t.trading_date.isoformat() for t in single_trades if t.entry_order_id in gt_entry_oids
    )
    detected_spike_days = set(res.metrics["spike_days"])

    day_tp = len(detected_spike_days & gt_planted_days)
    day_prec = day_tp / len(detected_spike_days) if detected_spike_days else 0.0
    day_rec = day_tp / len(gt_planted_days) if gt_planted_days else 0.0

    print("\n--- single_overtrading.csv Day-Level Evaluation ---")
    print(f"Planted spike days:  {sorted(gt_planted_days)}")
    print(f"Detected spike days: {sorted(detected_spike_days)}")
    print(f"Day Precision: {day_prec:.3f}")
    print(f"Day Recall:    {day_rec:.3f}")

    assert day_prec >= 0.8, f"Day precision {day_prec:.3f} < 0.8"
    assert day_rec >= 0.6, f"Day recall {day_rec:.3f} < 0.6"

    # b) Trade level evaluation
    detected_entry_oids = set(
        t.entry_order_id for t in single_trades if t.trade_id in res.flagged_trade_ids
    )
    trade_tp = len(detected_entry_oids & gt_entry_oids)
    trade_prec = trade_tp / len(detected_entry_oids) if detected_entry_oids else 0.0
    trade_rec = trade_tp / len(gt_entry_oids) if gt_entry_oids else 0.0

    print("\n--- single_overtrading.csv Trade-Level Evaluation ---")
    print(f"Detector excess count:     {len(detected_entry_oids)}")
    print(f"Ground-truth excess count: {len(gt_entry_oids)}")
    print(f"Trade Precision: {trade_prec:.3f}")
    print(f"Trade Recall:    {trade_rec:.3f}")
    print(
        "Explanation of trade-level gap: The detector keeps the earliest keep_n trades "
        "(ceil(median_daily)) on each spike day, marking all subsequent entries as excess. "
        "The synthetic generator planted excess trades at the tail of selected days after a "
        "variable number of baseline trades (len(existing) >= 3, median_daily=4). Small "
        "discrepancies arise when a day had fewer than 4 baseline trades before planting, so "
        "the detector's keep_n=4 keeps the first planted trade as 'normal session', creating "
        "a slight offset between generator-planted excess trades and detector-flagged "
        "excess trades."
    )

    # c) Cost evaluation
    injected_loss = gt_ot["injected_loss_inr"]
    print(f"Estimated Cost: ₹{res.estimated_cost_inr:,.2f}")
    print(f"Injected Loss:  ₹{injected_loss:,.2f}")
    print(
        "Explanation of injected_loss_inr: The generator creates excess trades on spike days "
        "and by construction forces each excess trade to suffer an exit price drop of 10-35% "
        "(choppy overtrading loss). Injected loss is the sum of absolute losses of planted "
        "excess trades. The detector measures net loss on all flagged excess trades "
        "(winners offset losers)."
    )
    assert (
        0.5 * injected_loss <= res.estimated_cost_inr <= 2.0 * injected_loss
    ), f"Cost ₹{res.estimated_cost_inr} out of bounds for injected ₹{injected_loss}"

    # 3. mixed.csv
    mixed_trades = pair_orders(parse_orders(Path("data/datasets/mixed.csv")).orders).trades
    with open("data/ground_truth/mixed.json") as f:
        mixed_gt = json.load(f)["habits"]["overtrading"]

    mixed_res = detector.detect(mixed_trades)
    assert mixed_res is not None, "overtrading failed to fire on mixed.csv"

    m_gt_entry_oids = set(mixed_gt["entry_order_ids"])
    m_gt_planted_days = set(
        t.trading_date.isoformat() for t in mixed_trades if t.entry_order_id in m_gt_entry_oids
    )
    m_detected_spike_days = set(mixed_res.metrics["spike_days"])
    m_day_tp = len(m_detected_spike_days & m_gt_planted_days)
    m_day_prec = m_day_tp / len(m_detected_spike_days) if m_detected_spike_days else 0.0
    m_day_rec = m_day_tp / len(m_gt_planted_days) if m_gt_planted_days else 0.0

    m_detected_entry_oids = set(
        t.entry_order_id for t in mixed_trades if t.trade_id in mixed_res.flagged_trade_ids
    )
    m_trade_tp = len(m_detected_entry_oids & m_gt_entry_oids)
    m_trade_prec = m_trade_tp / len(m_detected_entry_oids) if m_detected_entry_oids else 0.0
    m_trade_rec = m_trade_tp / len(m_gt_entry_oids) if m_gt_entry_oids else 0.0

    # Overlaps with holding_losers and revenge_trading
    hl_res = HoldingLosersDetector().detect(mixed_trades)
    rt_res = RevengeTradingDetector().detect(mixed_trades)
    hl_flagged = set(hl_res.flagged_trade_ids) if hl_res else set()
    rt_flagged = set(rt_res.flagged_trade_ids) if rt_res else set()
    ot_flagged = set(mixed_res.flagged_trade_ids)

    print("\n--- mixed.csv Evaluation ---")
    print(f"Day Precision:   {m_day_prec:.3f}, Day Recall: {m_day_rec:.3f}")
    print(f"Trade Precision: {m_trade_prec:.3f}, Trade Recall: {m_trade_rec:.3f}")
    print(f"Estimated Cost:  ₹{mixed_res.estimated_cost_inr:,.2f}")
    print(f"Injected Loss:   ₹{mixed_gt['injected_loss_inr']:,.2f}")
    print(f"Overlap with holding_losers:  {len(ot_flagged & hl_flagged)} trades")
    print(f"Overlap with revenge_trading: {len(ot_flagged & rt_flagged)} trades")

    # 4. Report other single_* datasets
    print("\n--- Other Single Habit Datasets ---")
    for ds_name in [
        "single_holding_losers",
        "single_revenge_trading",
        "single_oversizing",
        "single_averaging_down",
    ]:
        ds_trades = pair_orders(parse_orders(Path(f"data/datasets/{ds_name}.csv")).orders).trades
        ds_res = detector.detect(ds_trades)
        status_str = f"FIRED (₹{ds_res.estimated_cost_inr:,.2f})" if ds_res else "None"
        print(f"{ds_name}: {status_str}")


def test_overtrading_multi_seed_robustness() -> None:
    """Verify multi-seed robustness across 30 clean months and 30 planted months."""
    detector = OvertradingDetector()

    # 30 clean months with fresh seeds (730 to 759)
    clean_fired = 0
    for s in range(730, 760):
        csv_txt, _ = generate_dataset_in_memory(seed=s)
        orders = parse_orders(csv_txt).orders
        trades = pair_orders(orders).trades
        if detector.detect(trades) is not None:
            clean_fired += 1

    clean_fraction = clean_fired / 30.0
    print(f"\nMulti-seed clean months fired: {clean_fired}/30 ({clean_fraction:.1%})")
    assert clean_fired <= 1, f"Clean months fired {clean_fired}/30 times (> 1)"

    # 30 planted months with fresh seeds (830 to 859)
    planted_fired = 0
    for s in range(830, 860):
        csv_txt, _ = generate_dataset_in_memory(
            seed=s, habits_config={"overtrading": "medium"}
        )
        orders = parse_orders(csv_txt).orders
        trades = pair_orders(orders).trades
        if detector.detect(trades) is not None:
            planted_fired += 1

    detection_rate = planted_fired / 30.0
    print(f"Multi-seed planted months detected: {planted_fired}/30 ({detection_rate:.1%})")
    assert detection_rate >= 0.8, f"Detection rate {detection_rate:.1%} < 80% ({planted_fired}/30)"



# =====================================================================
# SECTION 2b: RevengeTradingDetector — Lots-Based Size Tests (Step 5c-fix)
# =====================================================================


def _make_rt_trade_ls(
    trade_id: str,
    entry_time: datetime,
    exit_time: datetime,
    quantity: int,
    lot_size: int,
    gross_pnl: float,
    entry_order_id: str,
    exit_order_id: str,
    symbol: str = "NIFTY24OCT25000CE",
    is_add_on: bool = False,
    is_partial_exit: bool = False,
) -> Trade:
    """Helper for lot-size-aware revenge trading tests."""
    return Trade(
        trade_id=trade_id,
        symbol=symbol,
        instrument_type="CE",
        strike=25000.0,
        expiry=date(2024, 10, 31),
        direction="LONG",
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=100.0,
        exit_price=100.0 + (gross_pnl / quantity) if quantity > 0 else 100.0,
        quantity=quantity,
        lot_size=lot_size,
        hold_minutes=(exit_time - entry_time).total_seconds() / 60.0,
        gross_pnl=gross_pnl,
        entry_order_id=entry_order_id,
        exit_order_id=exit_order_id,
        is_partial_exit=is_partial_exit,
        is_add_on=is_add_on,
        trading_date=entry_time.date(),
    )


def _build_lots_trades(
    prior_qty: int,
    prior_lot_size: int,
    entry_qty: int,
    entry_lot_size: int,
    prior_symbol: str = "NIFTY24OCT25000CE",
    entry_symbol: str = "NIFTY24OCT25000CE",
    n_repeat: int = 3,
) -> "list[Trade]":
    """Build n_repeat revenge pairs: prior loss immediately followed by re-entry."""
    base = datetime(2024, 10, 7, 9, 30, tzinfo=IST)
    trades = []
    for i in range(n_repeat):
        day_offset = timedelta(days=i)
        t_base = base + day_offset
        prior_exit = t_base + timedelta(minutes=10)
        entry_entry = prior_exit  # gap = 0 minutes
        entry_exit = prior_exit + timedelta(minutes=10)

        trades.append(_make_rt_trade_ls(
            trade_id=f"PR{i}",
            entry_time=t_base,
            exit_time=prior_exit,
            quantity=prior_qty,
            lot_size=prior_lot_size,
            gross_pnl=-1000.0,
            entry_order_id=f"EPR{i}",
            exit_order_id=f"XPR{i}",
            symbol=prior_symbol,
        ))
        trades.append(_make_rt_trade_ls(
            trade_id=f"EN{i}",
            entry_time=entry_entry,
            exit_time=entry_exit,
            quantity=entry_qty,
            lot_size=entry_lot_size,
            gross_pnl=-2000.0,
            entry_order_id=f"EEN{i}",
            exit_order_id=f"XEN{i}",
            symbol=entry_symbol,
        ))
    return trades


def test_revenge_trading_cross_instrument_1lot_not_flagged() -> None:
    """1-lot BANKNIFTY loss followed by 1-lot NIFTY entry must NOT be flagged.

    Raw quantities: 35 vs 75 -> ratio 2.14 >= 1.5 (would fire with old code).
    In lots: 1.0 vs 1.0 -> ratio 1.0 < 1.5 (correctly suppressed).
    """
    trades = _build_lots_trades(
        prior_qty=35,
        prior_lot_size=35,
        entry_qty=75,
        entry_lot_size=75,
        prior_symbol="BANKNIFTY24OCT51000PE",
        entry_symbol="NIFTY24OCT25000CE",
    )
    detector = RevengeTradingDetector()
    result = detector.detect(trades)
    assert result is None, (
        f"Detector fired cross-instrument 1-lot vs 1-lot: "
        f"flagged={getattr(result, 'flagged_trade_ids', None)}"
    )


def test_revenge_trading_same_instrument_1lot_then_2lot_flagged() -> None:
    """NIFTY 1-lot loss then NIFTY 2-lot entry IS flagged (2.0 >= 1.5)."""
    trades = _build_lots_trades(
        prior_qty=75,
        prior_lot_size=75,
        entry_qty=150,
        entry_lot_size=75,
    )
    detector = RevengeTradingDetector()
    result = detector.detect(trades)
    assert result is not None, "Detector failed to fire on NIFTY 1-lot -> 2-lot (ratio 2.0)"
    flagged = set(result.flagged_trade_ids)
    assert all(f"EN{i}" in flagged for i in range(3)), (
        f"Expected all EN0-EN2 flagged; got {sorted(flagged)}"
    )


def test_revenge_trading_2lots_then_3lots_flagged() -> None:
    """NIFTY 2-lot loss then NIFTY 3-lot entry IS flagged (3/2 = 1.5 >= 1.5)."""
    trades = _build_lots_trades(
        prior_qty=150,
        prior_lot_size=75,
        entry_qty=225,
        entry_lot_size=75,
    )
    detector = RevengeTradingDetector()
    result = detector.detect(trades)
    assert result is not None, "Detector failed to fire on NIFTY 2-lot -> 3-lot (ratio 1.5)"
    flagged = set(result.flagged_trade_ids)
    assert all(f"EN{i}" in flagged for i in range(3)), (
        f"Expected all EN0-EN2 flagged; got {sorted(flagged)}"
    )


def test_revenge_trading_same_instrument_lots_same_as_old_raw_behavior() -> None:
    """Same-instrument trades: lots ratio equals raw-quantity ratio exactly.

    NIFTY prior 1 lot (75 qty) -> NIFTY entry 2 lots (150 qty):
    raw ratio = 150/75 = 2.0, lots ratio = 2/1 = 2.0 -- same result.
    avg_size_multiple must equal 2.0.
    """
    trades = _build_lots_trades(
        prior_qty=75,
        prior_lot_size=75,
        entry_qty=150,
        entry_lot_size=75,
    )
    detector = RevengeTradingDetector()
    result = detector.detect(trades)
    assert result is not None, "Expected detector to fire but returned None"
    assert abs(result.metrics["avg_size_multiple"] - 2.0) < 0.01, (
        f"Expected avg_size_multiple=2.0, got {result.metrics['avg_size_multiple']}"
    )


def test_revenge_trading_benchmark_datasets_after_lots_fix() -> None:
    """After the lots fix, cross-instrument FPs on mixed.csv must be gone.

    Previously P0082, P0087, P0113 were false positives (BANKNIFTY 1-lot prior
    vs NIFTY 1-lot entry). After the fix precision must be >= 0.8 and recall >= 0.6.
    """
    import json
    from pathlib import Path

    detector = RevengeTradingDetector()
    mixed_orders = parse_orders(Path("data/datasets/mixed.csv")).orders
    mixed_trades = pair_orders(mixed_orders).trades

    eid_to_pid = {t.entry_order_id: t.trade_id for t in mixed_trades}

    result = detector.detect(mixed_trades)
    assert result is not None, "Detector failed to fire on mixed.csv"

    flagged = set(result.flagged_trade_ids)

    with open("data/ground_truth/mixed.json") as fh:
        gt = json.load(fh)
    gt_entry_oids = set(gt["habits"]["revenge_trading"]["entry_order_ids"])
    gt_pids = {eid_to_pid[e] for e in gt_entry_oids if e in eid_to_pid}

    fp_ids = flagged - gt_pids
    tp = len(flagged & gt_pids)
    fp = len(fp_ids)
    fn = len(gt_pids - flagged)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    print("\n--- mixed.csv after lots fix ---")
    print(f"  flagged={sorted(flagged)}")
    print(f"  gt_pids={sorted(gt_pids)}")
    print(f"  TP={tp}, FP={fp}, FN={fn}")
    print(f"  precision={precision:.3f}, recall={recall:.3f}")
    print(f"  FP ids: {sorted(fp_ids)}")

    assert precision >= 0.8, f"Precision {precision:.3f} < 0.8 after lots fix"
    assert recall >= 0.6, f"Recall {recall:.3f} < 0.6 after lots fix"

# =====================================================================
# SECTION 4: OversizingDetector Tests (Step 5d)
# =====================================================================


def _make_os_trade(
    trade_id: str,
    entry_time: datetime,
    exit_time: datetime,
    quantity: int,
    lot_size: int,
    gross_pnl: float,
    entry_order_id: str,
    exit_order_id: str,
    symbol: str = "NIFTY24OCT25000CE",
    is_add_on: bool = False,
    is_partial_exit: bool = False,
) -> Trade:
    """Helper for oversizing detector tests."""
    return Trade(
        trade_id=trade_id,
        symbol=symbol,
        instrument_type="CE",
        strike=25000.0,
        expiry=date(2024, 10, 31),
        direction="LONG",
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=100.0,
        exit_price=100.0 + (gross_pnl / quantity) if quantity > 0 else 100.0,
        quantity=quantity,
        lot_size=lot_size,
        hold_minutes=(exit_time - entry_time).total_seconds() / 60.0,
        gross_pnl=gross_pnl,
        entry_order_id=entry_order_id,
        exit_order_id=exit_order_id,
        is_partial_exit=is_partial_exit,
        is_add_on=is_add_on,
        trading_date=entry_time.date(),
    )


def _build_os_base(
    seed_start: int = 1,
    n_normal: int = 20,
    lot_size: int = 75,
    normal_qty: int = 75,
    normal_pnl: float = 500.0,
) -> "tuple[list[Trade], datetime]":
    """Build n_normal 1-lot trades spread across sequential days.

    Returns (trades, next_available_time) so callers can add streak + oversized trades.
    Each trade: entry at 09:30, exit at 09:50 (20 min hold).
    Alternates win/loss to avoid creating accidental streaks.
    """
    trades = []
    base_date = date(2024, 10, 1)
    for i in range(n_normal):
        # Spread across days: 2 trades per day so we have enough days
        day_offset = i // 2
        minute_offset = (i % 2) * 60  # 0 or 60 min apart within a day
        d = base_date.replace(day=base_date.day + day_offset)
        entry = datetime(d.year, d.month, d.day, 9, 30, tzinfo=IST) + timedelta(
            minutes=minute_offset
        )
        ex = entry + timedelta(minutes=20)
        pnl = normal_pnl if i % 2 == 0 else -normal_pnl * 0.8  # alternating win/loss
        trades.append(
            _make_os_trade(
                trade_id=f"N{seed_start + i}",
                entry_time=entry,
                exit_time=ex,
                quantity=normal_qty,
                lot_size=lot_size,
                gross_pnl=pnl,
                entry_order_id=f"EN{seed_start + i}",
                exit_order_id=f"XN{seed_start + i}",
            )
        )
    last = trades[-1]
    next_time = last.exit_time + timedelta(minutes=60)
    return trades, next_time


def _append_streak_then_oversized(
    base_trades: list[Trade],
    next_time: datetime,
    win_streak: bool,
    streak_pnl: float,
    oversized_qty: int,
    lot_size: int,
    oversized_pnl: float,
    tag: str,
    symbol: str = "NIFTY24OCT25000CE",
) -> "tuple[list[Trade], datetime]":
    """Append 2 streak trades then 1 oversized trade, returning updated next_time."""
    t = next_time
    for i in range(2):
        ex = t + timedelta(minutes=20)
        pnl = abs(streak_pnl) if win_streak else -abs(streak_pnl)
        base_trades.append(
            _make_os_trade(
                trade_id=f"STR_{tag}_{i}",
                entry_time=t,
                exit_time=ex,
                quantity=75,
                lot_size=lot_size,
                gross_pnl=pnl,
                entry_order_id=f"ESTR_{tag}_{i}",
                exit_order_id=f"XSTR_{tag}_{i}",
                symbol=symbol,
            )
        )
        t = ex + timedelta(minutes=5)

    # Oversized trade after the streak
    ex_os = t + timedelta(minutes=20)
    base_trades.append(
        _make_os_trade(
            trade_id=f"OS_{tag}",
            entry_time=t,
            exit_time=ex_os,
            quantity=oversized_qty,
            lot_size=lot_size,
            gross_pnl=oversized_pnl,
            entry_order_id=f"EOS_{tag}",
            exit_order_id=f"XOS_{tag}",
            symbol=symbol,
        )
    )
    return base_trades, ex_os + timedelta(minutes=60)


def test_oversizing_fires_constructed_case() -> None:
    """Detector fires on a hand-built case; verify exact cost, IDs, and metrics.

    Setup:
    - 20 normal 1-lot trades (lot_size=75, qty=75), alternating +500/-400 pnl.
    - 3 streak+oversized groups: each has a 2-trade win/loss streak then a 3-lot
      oversized entry (qty=225, lot_size=75) that loses.

    median_lots = 1.0  (all normals are 1 lot; oversized don't shift median
                         because only 3 oversized out of 23 entries)
    oversized size_lots = 3.0 > 2.0 * 1.0 = 2.0 -> flagged
    cost per flagged = max(0, -pnl) * (1 - 1.0/3.0) = loss * (2/3)
    """
    from app.detectors.oversizing import OversizingDetector

    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # 3 groups: loss streak -> oversized loss
    oversized_loss = -6000.0
    for tag in ["A", "B", "C"]:
        trades, t = _append_streak_then_oversized(
            trades,
            t,
            win_streak=False,
            streak_pnl=500.0,
            oversized_qty=225,  # 3 lots
            lot_size=75,
            oversized_pnl=oversized_loss,
            tag=tag,
        )

    det = OversizingDetector()
    res = det.detect(trades)

    assert res is not None, "Expected detector to fire"
    assert res.key == "oversizing"
    assert res.name == "Betting much bigger after a streak"

    # All 3 oversized trade IDs should be flagged
    assert "OS_A" in res.flagged_trade_ids
    assert "OS_B" in res.flagged_trade_ids
    assert "OS_C" in res.flagged_trade_ids

    # No normal trades flagged
    for i in range(20):
        assert f"N{1 + i}" not in res.flagged_trade_ids

    # Cost: max(0, 6000) * (1 - 1/3) = 6000 * 2/3 = 4000 per trade; 3 trades = 12000
    expected_cost = 3 * abs(oversized_loss) * (1 - 1.0 / 3.0)
    assert abs(res.estimated_cost_inr - expected_cost) < 1.0, (
        f"Expected cost ~{expected_cost:.2f}, got {res.estimated_cost_inr}"
    )

    assert res.metrics["flagged_entries"] == 3
    assert res.metrics["median_lots"] == 1.0
    assert abs(res.metrics["avg_size_multiple"] - 3.0) < 0.01
    assert res.metrics["after_loss_streak"] == 3
    assert res.metrics["after_win_streak"] == 0


def test_oversizing_exact_2x_not_flagged_just_above_is() -> None:
    """Exactly 2.0× median_lots is NOT flagged; strictly above 2.0× is."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # Add 2 win-streak trades
    for i in range(2):
        ex = t + timedelta(minutes=20)
        trades.append(_make_os_trade(f"STR_E{i}", t, ex, 75, 75, 500.0, f"ESTRE{i}", f"XSTRE{i}"))
        t = ex + timedelta(minutes=5)

    # Exactly 2.0× median (1.0 lot → 2.0 lots): NOT flagged
    ex2 = t + timedelta(minutes=20)
    trades.append(_make_os_trade("EXACT2", t, ex2, 150, 75, -3000.0, "EEXACT2", "XEXACT2"))
    t = ex2 + timedelta(minutes=60)

    # Strictly > 2.0× (3 lots): FLAGGED — but need a fresh streak for it
    for i in range(2):
        ex = t + timedelta(minutes=20)
        trades.append(_make_os_trade(f"STR_F{i}", t, ex, 75, 75, 500.0, f"ESTRF{i}", f"XSTRF{i}"))
        t = ex + timedelta(minutes=5)

    ex3 = t + timedelta(minutes=20)
    trades.append(_make_os_trade("ABOVE2", t, ex3, 225, 75, -4500.0, "EABOVE2", "XABOVE2"))

    # And need 2 more flagged entries to reach MIN_FLAGGED=3
    t = ex3 + timedelta(minutes=60)
    for tag in ["G1", "G2"]:
        for j in range(2):
            ex = t + timedelta(minutes=20)
            trades.append(
                _make_os_trade(
                    f"STR_{tag}_{j}", t, ex, 75, 75, 500.0, f"ESTR_{tag}_{j}", f"XSTR_{tag}_{j}"
                )
            )
            t = ex + timedelta(minutes=5)
        ex_os = t + timedelta(minutes=20)
        trades.append(
            _make_os_trade(f"OS_{tag}", t, ex_os, 225, 75, -4500.0, f"EOS_{tag}", f"XOS_{tag}")
        )
        t = ex_os + timedelta(minutes=60)

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)

    assert res is not None
    assert "EXACT2" not in res.flagged_trade_ids, "Exactly 2.0× should NOT be flagged"
    assert "ABOVE2" in res.flagged_trade_ids, "Strictly > 2.0× should be flagged"


def test_oversizing_big_size_no_streak_not_flagged() -> None:
    """Large position with no 2-trade streak is NOT flagged."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # One big trade but NO preceding streak (only 1 prior closing event at time of entry,
    # since we insert it right after base_trades — but base trades alternate win/loss
    # so the last two prior closings are win then loss -> not a streak).
    # However the alternating pattern means last 2 are: win (N20), loss (N19) -> no streak.
    ex = t + timedelta(minutes=20)
    trades.append(
        _make_os_trade("BIGNOSTREAK", t, ex, 300, 75, -8000.0, "EBIGNOSTREAK", "XBIGNOSTREAK")
    )

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)

    # With only 1 oversized trade (and it's not flagged due to no streak),
    # we expect None (< MIN_FLAGGED=3).
    # The key property: "BIGNOSTREAK" must not appear in any flagged list.
    if res is not None:
        assert "BIGNOSTREAK" not in res.flagged_trade_ids, (
            "Big-size trade with no streak must not be flagged"
        )


def test_oversizing_streak_of_only_1_not_flagged() -> None:
    """A streak of only 1 prior loss/win is not a streak (need STREAK_LEN=2)."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # Only 1 win prior to the oversized entry
    ex = t + timedelta(minutes=20)
    trades.append(_make_os_trade("STR1", t, ex, 75, 75, 500.0, "ESTR1", "XSTR1"))
    t = ex + timedelta(minutes=5)

    ex2 = t + timedelta(minutes=20)
    trades.append(_make_os_trade("OS_1STR", t, ex2, 300, 75, -8000.0, "EOS_1STR", "XOS_1STR"))

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)

    if res is not None:
        assert "OS_1STR" not in res.flagged_trade_ids, (
            "Oversized entry after only 1-trade streak must not be flagged"
        )


def test_oversizing_mixed_win_loss_pair_not_a_streak() -> None:
    """A win followed by a loss (or vice versa) is NOT a streak."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # Win then loss
    ex = t + timedelta(minutes=20)
    trades.append(_make_os_trade("MIX1", t, ex, 75, 75, 500.0, "EMIX1", "XMIX1"))
    t = ex + timedelta(minutes=5)
    ex2 = t + timedelta(minutes=20)
    trades.append(_make_os_trade("MIX2", t, ex2, 75, 75, -400.0, "EMIX2", "XMIX2"))
    t = ex2 + timedelta(minutes=5)

    ex3 = t + timedelta(minutes=20)
    trades.append(_make_os_trade("OS_MIX", t, ex3, 300, 75, -8000.0, "EOS_MIX", "XOS_MIX"))

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)

    if res is not None:
        assert "OS_MIX" not in res.flagged_trade_ids, (
            "Oversized entry after win+loss pair must not be flagged"
        )


def test_oversizing_zero_pnl_breaks_streak() -> None:
    """A zero-pnl closing event between two wins/losses breaks the streak."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # Win, zero-pnl, win -> last 2 are (zero, win) -> not a streak
    ex = t + timedelta(minutes=20)
    trades.append(_make_os_trade("WIN1", t, ex, 75, 75, 500.0, "EWIN1", "XWIN1"))
    t = ex + timedelta(minutes=5)
    ex2 = t + timedelta(minutes=20)
    trades.append(_make_os_trade("ZERO1", t, ex2, 75, 75, 0.0, "EZERO1", "XZERO1"))
    t = ex2 + timedelta(minutes=5)
    ex3 = t + timedelta(minutes=20)
    trades.append(_make_os_trade("WIN2", t, ex3, 75, 75, 500.0, "EWIN2", "XWIN2"))
    t = ex3 + timedelta(minutes=5)

    ex4 = t + timedelta(minutes=20)
    trades.append(_make_os_trade("OS_ZERO", t, ex4, 300, 75, -8000.0, "EOS_ZERO", "XOS_ZERO"))

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)

    if res is not None:
        assert "OS_ZERO" not in res.flagged_trade_ids, (
            "Zero-pnl event must break streak so oversized trade after it is not flagged"
        )


def test_oversizing_win_streak_and_loss_streak_both_flag() -> None:
    """Both win-streak and loss-streak oversized entries get flagged."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # Win streak -> oversized loss
    for i in range(2):
        ex = t + timedelta(minutes=20)
        trades.append(_make_os_trade(f"WSTR{i}", t, ex, 75, 75, 600.0, f"EWSTR{i}", f"XWSTR{i}"))
        t = ex + timedelta(minutes=5)
    ex_w = t + timedelta(minutes=20)
    trades.append(_make_os_trade("OS_WIN", t, ex_w, 225, 75, -5000.0, "EOS_WIN", "XOS_WIN"))
    t = ex_w + timedelta(minutes=60)

    # Loss streak -> oversized loss
    for i in range(2):
        ex = t + timedelta(minutes=20)
        trades.append(_make_os_trade(f"LSTR{i}", t, ex, 75, 75, -600.0, f"ELSTR{i}", f"XLSTR{i}"))
        t = ex + timedelta(minutes=5)
    ex_l = t + timedelta(minutes=20)
    trades.append(_make_os_trade("OS_LOSS", t, ex_l, 225, 75, -5000.0, "EOS_LOSS", "XOS_LOSS"))
    t = ex_l + timedelta(minutes=60)

    # One more to reach MIN_FLAGGED=3
    for i in range(2):
        ex = t + timedelta(minutes=20)
        trades.append(
            _make_os_trade(f"WSTR2_{i}", t, ex, 75, 75, 600.0, f"EWSTR2_{i}", f"XWSTR2_{i}")
        )
        t = ex + timedelta(minutes=5)
    ex_w2 = t + timedelta(minutes=20)
    trades.append(_make_os_trade("OS_WIN2", t, ex_w2, 225, 75, -5000.0, "EOS_WIN2", "XOS_WIN2"))

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)

    assert res is not None
    assert "OS_WIN" in res.flagged_trade_ids, "Win-streak oversized entry must be flagged"
    assert "OS_LOSS" in res.flagged_trade_ids, "Loss-streak oversized entry must be flagged"
    assert res.metrics["after_win_streak"] >= 1
    assert res.metrics["after_loss_streak"] >= 1


def test_oversizing_same_lots_nifty_banknifty_not_flagged() -> None:
    """1-lot NIFTY (qty=75) and 1-lot BANKNIFTY (qty=35) are the same size in lots.

    A NIFTY 1-lot entry after a BANKNIFTY streak must NOT be flagged as oversized.
    """
    # Build 20 BANKNIFTY 1-lot normal trades
    trades, t = _build_os_base(n_normal=20, lot_size=35, normal_qty=35)

    # 2-trade BANKNIFTY win streak
    for i in range(2):
        ex = t + timedelta(minutes=20)
        trades.append(
            _make_os_trade(
                f"BSTR{i}",
                t,
                ex,
                35,
                35,
                500.0,
                f"EBSTR{i}",
                f"XBSTR{i}",
                symbol="BANKNIFTY24OCT51000PE",
            )
        )
        t = ex + timedelta(minutes=5)

    # NIFTY 1-lot entry (qty=75 but lot_size=75 -> 1 lot == same as BANKNIFTY 1-lot)
    ex_n = t + timedelta(minutes=20)
    trades.append(
        _make_os_trade(
            "NIFTY_1LOT",
            t,
            ex_n,
            75,
            75,
            -3000.0,
            "ENIFTY_1LOT",
            "XNIFTY_1LOT",
            symbol="NIFTY24OCT25000CE",
        )
    )

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)

    # median_lots = 1.0; NIFTY entry = 1.0 lot -> NOT > 2.0 * 1.0 -> not flagged
    if res is not None:
        assert "NIFTY_1LOT" not in res.flagged_trade_ids, (
            "1-lot NIFTY after BANKNIFTY streak must not be flagged (same size in lots)"
        )


def test_oversizing_multi_slice_entry_aggregated() -> None:
    """Multi-slice entry (partial exit creating 2 trades with same entry_order_id)
    has its total lots aggregated before the size check."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # 2-trade win streak
    for i in range(2):
        ex = t + timedelta(minutes=20)
        trades.append(_make_os_trade(f"MSTR{i}", t, ex, 75, 75, 500.0, f"EMSTR{i}", f"XMSTR{i}"))
        t = ex + timedelta(minutes=5)

    # 2 slices with the same entry_order_id (partial exits), each 2 lots = 4 lots total
    entry_time = t
    ex1 = t + timedelta(minutes=10)
    ex2 = t + timedelta(minutes=20)
    trades.append(
        _make_os_trade(
            "SLICE_A", entry_time, ex1, 150, 75, -2000.0, "EMULTI", "XMULTI_A", is_partial_exit=True
        )
    )
    trades.append(
        _make_os_trade(
            "SLICE_B", entry_time, ex2, 150, 75, -2000.0, "EMULTI", "XMULTI_B", is_partial_exit=True
        )
    )
    t = ex2 + timedelta(minutes=60)

    # Need 2 more flagged entries to reach MIN_FLAGGED=3
    for tag in ["M1", "M2"]:
        for j in range(2):
            ex = t + timedelta(minutes=20)
            trades.append(
                _make_os_trade(
                    f"STR_{tag}_{j}", t, ex, 75, 75, 500.0, f"ESTR_{tag}_{j}", f"XSTR_{tag}_{j}"
                )
            )
            t = ex + timedelta(minutes=5)
        ex_os = t + timedelta(minutes=20)
        trades.append(
            _make_os_trade(f"OS_{tag}", t, ex_os, 225, 75, -4000.0, f"EOS_{tag}", f"XOS_{tag}")
        )
        t = ex_os + timedelta(minutes=60)

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)

    assert res is not None
    # Both slices of EMULTI should appear in flagged_trade_ids (4 lots > 2.0 * median_lots)
    assert "SLICE_A" in res.flagged_trade_ids, "Slice A of multi-slice entry must be flagged"
    assert "SLICE_B" in res.flagged_trade_ids, "Slice B of multi-slice entry must be flagged"


def test_oversizing_addon_entries_skipped() -> None:
    """Add-on entries (is_add_on=True) are excluded from entry aggregation."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # 2-trade streak
    for i in range(2):
        ex = t + timedelta(minutes=20)
        trades.append(_make_os_trade(f"ASTR{i}", t, ex, 75, 75, 500.0, f"EASTR{i}", f"XASTR{i}"))
        t = ex + timedelta(minutes=5)

    # Add-on entry (large qty but is_add_on=True) -> must not be flagged
    ex_ao = t + timedelta(minutes=20)
    trades.append(
        _make_os_trade(
            "ADDON_BIG", t, ex_ao, 300, 75, -5000.0, "EADDON_BIG", "XADDON_BIG", is_add_on=True
        )
    )

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)

    if res is not None:
        assert "ADDON_BIG" not in res.flagged_trade_ids, (
            "Add-on entry must not appear in flagged_trade_ids"
        )


def test_oversizing_fewer_than_20_entries_returns_none() -> None:
    """Fewer than MIN_ENTRIES (20) entries -> return None."""
    trades, t = _build_os_base(n_normal=19, lot_size=75, normal_qty=75)

    # Add a clearly oversized trade after a streak - still only 20 entries counting it
    for i in range(2):
        ex = t + timedelta(minutes=20)
        trades.append(_make_os_trade(f"STR{i}", t, ex, 75, 75, 500.0, f"ESTR{i}", f"XSTR{i}"))
        t = ex + timedelta(minutes=5)
    # Total now: 19 + 2 + 1 = 22 entries... need to test with exactly <20 non-addon entries
    # Reset: use only 10 normals
    trades2, t2 = _build_os_base(n_normal=10, lot_size=75, normal_qty=75)
    for i in range(2):
        ex = t2 + timedelta(minutes=20)
        trades2.append(
            _make_os_trade(f"S2STR{i}", t2, ex, 75, 75, 500.0, f"ES2STR{i}", f"XS2STR{i}")
        )
        t2 = ex + timedelta(minutes=5)
    ex_os = t2 + timedelta(minutes=20)
    trades2.append(_make_os_trade("OS_FEW", t2, ex_os, 300, 75, -5000.0, "EOS_FEW", "XOS_FEW"))

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    assert det.detect(trades2) is None, "Fewer than 20 entries must return None"


def test_oversizing_fewer_than_3_flagged_returns_none() -> None:
    """Fewer than MIN_FLAGGED (3) flagged entries -> return None."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # Only 2 oversized entries (need 3 to fire)
    for tag in ["X", "Y"]:
        for i in range(2):
            ex = t + timedelta(minutes=20)
            trades.append(
                _make_os_trade(
                    f"S_{tag}_{i}", t, ex, 75, 75, 600.0, f"ES_{tag}_{i}", f"XS_{tag}_{i}"
                )
            )
            t = ex + timedelta(minutes=5)
        ex_os = t + timedelta(minutes=20)
        trades.append(
            _make_os_trade(f"OS_{tag}", t, ex_os, 225, 75, -4000.0, f"EOS_{tag}", f"XOS_{tag}")
        )
        t = ex_os + timedelta(minutes=60)

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    assert det.detect(trades) is None, "Fewer than 3 flagged entries must return None"


def test_oversizing_winning_flagged_entries_contribute_zero_cost() -> None:
    """Flagged entries that are winners contribute 0 to estimated_cost_inr.
    If all flagged entries are profitable, estimated_cost_inr = 0 and None is returned.
    """
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)

    # 3 oversized entries all with positive PnL (winners)
    for tag in ["P1", "P2", "P3"]:
        for i in range(2):
            ex = t + timedelta(minutes=20)
            trades.append(
                _make_os_trade(
                    f"S_{tag}_{i}", t, ex, 75, 75, 500.0, f"ES_{tag}_{i}", f"XS_{tag}_{i}"
                )
            )
            t = ex + timedelta(minutes=5)
        ex_os = t + timedelta(minutes=20)
        trades.append(
            _make_os_trade(
                f"OS_{tag}",
                t,
                ex_os,
                225,
                75,
                +8000.0,  # winner!
                f"EOS_{tag}",
                f"XOS_{tag}",
            )
        )
        t = ex_os + timedelta(minutes=60)

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    res = det.detect(trades)
    # All winners -> cost = 0 -> return None
    assert res is None, "All winning flagged entries should result in None (cost=0)"


def test_oversizing_determinism() -> None:
    """Calling detect twice on the same input gives identical results."""
    trades, t = _build_os_base(n_normal=20, lot_size=75, normal_qty=75)
    for tag in ["D1", "D2", "D3"]:
        trades, t = _append_streak_then_oversized(
            trades,
            t,
            win_streak=True,
            streak_pnl=500.0,
            oversized_qty=225,
            lot_size=75,
            oversized_pnl=-5000.0,
            tag=tag,
        )

    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()
    r1 = det.detect(trades)
    r2 = det.detect(trades)
    assert r1 is not None and r2 is not None
    assert r1.estimated_cost_inr == r2.estimated_cost_inr
    assert r1.flagged_trade_ids == r2.flagged_trade_ids
    assert r1.metrics == r2.metrics
    assert r1.formula_note == r2.formula_note


def test_oversizing_benchmark_datasets() -> None:
    """Test OversizingDetector on benchmark datasets."""
    from pathlib import Path

    from app.detectors.holding_losers import HoldingLosersDetector
    from app.detectors.oversizing import OversizingDetector
    from app.detectors.overtrading import OvertradingDetector
    from app.detectors.revenge_trading import RevengeTradingDetector

    det = OversizingDetector()

    # 1. clean.csv: must return None
    clean_trades = pair_orders(parse_orders(Path("data/datasets/clean.csv")).orders).trades
    assert det.detect(clean_trades) is None, "oversizing falsely fired on clean.csv"

    # 2. single_oversizing.csv: must fire with P >= 0.8 and R >= 0.6
    single_trades = pair_orders(
        parse_orders(Path("data/datasets/single_oversizing.csv")).orders
    ).trades
    with open("data/ground_truth/single_oversizing.json") as f:
        gt_data = json.load(f)
    gt_os = gt_data["habits"]["oversizing"]

    res = det.detect(single_trades)
    assert res is not None, "oversizing failed to fire on single_oversizing.csv"

    true_oids = set(gt_os["entry_order_ids"])
    detected_oids = set(
        t.entry_order_id for t in single_trades if t.trade_id in res.flagged_trade_ids
    )
    tp = len(detected_oids & true_oids)
    precision = tp / len(detected_oids) if detected_oids else 0.0
    recall = tp / len(true_oids) if true_oids else 0.0
    injected_loss = gt_os["injected_loss_inr"]

    print("\n--- single_oversizing.csv Evaluation ---")
    print(f"Precision:       {precision:.3f}")
    print(f"Recall:          {recall:.3f}")
    print(f"Estimated Cost:  Rs {res.estimated_cost_inr:,.2f}")
    print(f"Injected Loss:   Rs {injected_loss:,.2f}")
    print(
        "injected_loss_inr for oversizing = the extra loss from the EXCESS quantity only. "
        "The generator sets new_lots to 3-4 (from 1), makes the trade lose 15-45%, then "
        "records (entry_price - exit_price) * (excess_qty) as the injected cost. "
        "The generator DOES force oversized trades to lose (exit_price set below entry_price)."
    )
    print(f"Metrics: {res.metrics}")

    assert precision >= 0.8, f"Precision {precision:.3f} < 0.8"
    assert recall >= 0.6, f"Recall {recall:.3f} < 0.6"
    assert 0.5 * injected_loss <= res.estimated_cost_inr <= 2.0 * injected_loss, (
        f"Cost Rs{res.estimated_cost_inr} out of [0.5x, 2x] injected Rs{injected_loss}"
    )

    # 3. Other datasets: print result; note any unplanted fires
    print("\n--- Other datasets ---")
    for ds_name in [
        "single_holding_losers",
        "single_revenge_trading",
        "single_overtrading",
        "single_averaging_down",
    ]:
        ds_path = Path(f"data/datasets/{ds_name}.csv")
        ds_trades = pair_orders(parse_orders(ds_path).orders).trades
        ds_res = det.detect(ds_trades)
        with open(f"data/ground_truth/{ds_name}.json") as f:
            ds_gt = json.load(f)
        planted = ds_gt["habits"]["oversizing"]["planted"]
        if ds_res is not None and not planted:
            # False positive - list flagged entries
            flagged_eoids = {
                t.entry_order_id for t in ds_trades if t.trade_id in ds_res.flagged_trade_ids
            }
            print(f"{ds_name}: FIRES (unplanted!) flagged_entry_oids={sorted(flagged_eoids)}")
        else:
            status = f"FIRES (Rs{ds_res.estimated_cost_inr:,.2f})" if ds_res else "None"
            print(f"{ds_name}: {status}")

    # 4. mixed.csv: report + overlap
    print("\n--- mixed.csv ---")
    mixed_trades = pair_orders(parse_orders(Path("data/datasets/mixed.csv")).orders).trades
    with open("data/ground_truth/mixed.json") as f:
        mixed_gt = json.load(f)
    mixed_res = det.detect(mixed_trades)
    mixed_planted = mixed_gt["habits"]["oversizing"]["planted"]
    print(f"oversizing planted in mixed: {mixed_planted}")
    if mixed_res is not None:
        eid_to_pid_m = {t.entry_order_id: t.trade_id for t in mixed_trades}
        gt_eoids_m = set(mixed_gt["habits"]["oversizing"]["entry_order_ids"])
        gt_pids_m = {eid_to_pid_m[e] for e in gt_eoids_m if e in eid_to_pid_m}
        flagged_m = set(mixed_res.flagged_trade_ids)
        tp_m = len(flagged_m & gt_pids_m)
        fp_m = flagged_m - gt_pids_m
        prec_m = tp_m / len(flagged_m) if flagged_m else 0.0
        rec_m = tp_m / len(gt_pids_m) if gt_pids_m else 0.0
        print(f"  FIRES: precision={prec_m:.3f} recall={rec_m:.3f} FP={sorted(fp_m)}")

        # Overlap with other detectors
        hl_res = HoldingLosersDetector().detect(mixed_trades)
        rt_res = RevengeTradingDetector().detect(mixed_trades)
        ot_res = OvertradingDetector().detect(mixed_trades)
        hl_flag = set(hl_res.flagged_trade_ids) if hl_res else set()
        rt_flag = set(rt_res.flagged_trade_ids) if rt_res else set()
        ot_flag = set(ot_res.flagged_trade_ids) if ot_res else set()
        print(f"  Overlap with holding_losers: {len(flagged_m & hl_flag)}")
        print(f"  Overlap with revenge_trading: {len(flagged_m & rt_flag)}")
        print(f"  Overlap with overtrading: {len(flagged_m & ot_flag)}")
    else:
        print("  None")


def test_oversizing_multi_seed_robustness() -> None:
    """Verify multi-seed robustness across 30 clean and 30 planted months."""
    from app.detectors.oversizing import OversizingDetector

    det = OversizingDetector()

    # 30 clean months: at most 1 fires
    clean_fired = 0
    for s in range(920, 950):
        csv_txt, _ = generate_dataset_in_memory(seed=s)
        trades = pair_orders(parse_orders(csv_txt).orders).trades
        if det.detect(trades) is not None:
            clean_fired += 1

    print(f"\nMulti-seed clean months fired: {clean_fired}/30 ({clean_fired / 30:.1%})")
    assert clean_fired <= 1, f"Clean months fired {clean_fired}/30 times (> 1)"

    # 30 planted months: detection >= 0.8
    planted_fired = 0
    for s in range(950, 980):
        csv_txt, _ = generate_dataset_in_memory(seed=s, habits_config={"oversizing": "medium"})
        trades = pair_orders(parse_orders(csv_txt).orders).trades
        if det.detect(trades) is not None:
            planted_fired += 1

    detection_rate = planted_fired / 30.0
    print(f"Multi-seed planted months detected: {planted_fired}/30 ({detection_rate:.1%})")
    assert detection_rate >= 0.8, f"Detection rate {detection_rate:.1%} < 80% ({planted_fired}/30)"
