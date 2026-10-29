"""Unit tests for synthetic data generator and baseline constraints."""

import csv
import json
import statistics
from datetime import datetime
from pathlib import Path

from data.generator import (
    BASELINE_MAX_DAILY_TO_MEDIAN_RATIO,
    BASELINE_MAX_DAILY_TRADES,
    BASELINE_MAX_LOTS,
    BASELINE_MIN_DAILY_TRADES,
    BASELINE_MIN_LOTS,
    BASELINE_MIN_POST_LOSS_ENTRY_MINUTES,
    CANONICAL_COLUMNS,
    DATASET_SPECIFICATIONS,
    SyntheticGenerator,
    generate_all,
)


def test_determinism_same_seed_identical_output(tmp_path: Path) -> None:
    """Verify that generating with the same seed produces identical orders and ground truth."""
    gen1 = SyntheticGenerator(seed=42)
    orders1, gt1 = gen1.generate_dataset(name="test", habits_config={"revenge_trading": "medium"})

    gen2 = SyntheticGenerator(seed=42)
    orders2, gt2 = gen2.generate_dataset(name="test", habits_config={"revenge_trading": "medium"})

    assert len(orders1) == len(orders2)
    assert gt1 == gt2
    for o1, o2 in zip(orders1, orders2, strict=True):
        assert o1.to_csv_dict() == o2.to_csv_dict()


def test_canonical_schema_columns(tmp_path: Path) -> None:
    """Verify all generated CSVs have exact canonical schema headers."""
    gen = SyntheticGenerator(seed=123)
    orders, _ = gen.generate_dataset(name="schema_test")
    csv_file = tmp_path / "schema_test.csv"

    with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        for o in orders:
            writer.writerow(o.to_csv_dict())

    with open(csv_file, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == CANONICAL_COLUMNS


def test_clean_baseline_constraints() -> None:
    """Verify clean.csv satisfies all strict baseline constraints."""
    csv_path = Path("data/datasets/clean.csv")
    assert csv_path.exists(), "clean.csv does not exist. Run make data first."

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        orders = list(reader)

    assert len(orders) > 0

    # Parse into paired trades (entry BUY followed by exit SELL in clean dataset)
    trades: list[dict[str, any]] = []
    i = 0
    while i < len(orders):
        entry = orders[i]
        assert entry["side"] == "BUY"
        assert entry["status"] == "COMPLETE"
        exit_order = orders[i + 1]
        assert exit_order["side"] == "SELL"
        assert exit_order["status"] == "COMPLETE"
        assert entry["symbol"] == exit_order["symbol"]
        assert int(entry["quantity"]) == int(exit_order["quantity"])

        entry_time = datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M:%S%z")
        exit_time = datetime.strptime(exit_order["timestamp"], "%Y-%m-%d %H:%M:%S%z")
        entry_price = float(entry["price"])
        exit_price = float(exit_order["price"])
        pnl = (exit_price - entry_price) * int(entry["quantity"])
        lots = int(entry["quantity"]) // int(entry["lot_size"])

        trades.append(
            {
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "lots": lots,
                "hold_minutes": (exit_time - entry_time).total_seconds() / 60.0,
            }
        )
        i += 2

    # 1. 3-6 trades per day (never above ~1.5x monthly median)
    trades_by_day: dict[str, int] = {}
    for t in trades:
        day_key = t["entry_time"].strftime("%Y-%m-%d")
        trades_by_day[day_key] = trades_by_day.get(day_key, 0) + 1

    daily_counts = list(trades_by_day.values())
    median_daily = statistics.median(daily_counts)
    for count in daily_counts:
        in_range = BASELINE_MIN_DAILY_TRADES <= count <= BASELINE_MAX_DAILY_TRADES
        assert in_range, (
            f"Daily count {count} violates range "
            f"[{BASELINE_MIN_DAILY_TRADES}, {BASELINE_MAX_DAILY_TRADES}]"
        )
        max_allowed = median_daily * BASELINE_MAX_DAILY_TO_MEDIAN_RATIO
        assert count <= max_allowed, f"Daily count {count} exceeds {max_allowed}"

    # 2. Fixed 1-2 lots with no size jump above 1.5x median
    lots_list = [t["lots"] for t in trades]
    median_lots = statistics.median(lots_list)
    for lots in lots_list:
        assert (
            BASELINE_MIN_LOTS <= lots <= BASELINE_MAX_LOTS
        ), f"Lots {lots} out of range [{BASELINE_MIN_LOTS}, {BASELINE_MAX_LOTS}]"
        assert lots <= median_lots * 1.5, f"Lots {lots} exceeds 1.5x median {median_lots}"

    # 3. Hold times for winners and losers drawn from same distribution
    win_holds = [t["hold_minutes"] for t in trades if t["pnl"] > 0]
    loss_holds = [t["hold_minutes"] for t in trades if t["pnl"] < 0]
    assert len(win_holds) > 0 and len(loss_holds) > 0
    # Medians should be within standard deviation
    assert abs(statistics.median(win_holds) - statistics.median(loss_holds)) <= 8.0

    # 4. At least 45 minutes between a loss and the next entry
    for idx in range(len(trades) - 1):
        curr = trades[idx]
        nxt = trades[idx + 1]
        if curr["pnl"] < 0 and curr["exit_time"].date() == nxt["entry_time"].date():
            gap = (nxt["entry_time"] - curr["exit_time"]).total_seconds() / 60.0
            assert (
                gap >= BASELINE_MIN_POST_LOSS_ENTRY_MINUTES - 0.01
            ), f"Gap after loss was {gap} min, expected >= {BASELINE_MIN_POST_LOSS_ENTRY_MINUTES}"

    # 5. One position open at a time (no overlap)
    for idx in range(len(trades) - 1):
        assert trades[idx]["exit_time"] <= trades[idx + 1]["entry_time"]


def test_single_habit_datasets_ground_truth() -> None:
    """Verify each single dataset has its planted habit non-empty and all others false."""
    single_names = [k for k in DATASET_SPECIFICATIONS if k.startswith("single_")]
    assert len(single_names) == 5

    for name in single_names:
        planted_key = name.replace("single_", "")
        gt_path = Path(f"data/ground_truth/{name}.json")
        assert gt_path.exists(), f"Ground truth {gt_path} not found"

        with open(gt_path, encoding="utf-8") as f:
            gt = json.load(f)

        assert gt["dataset"] == name
        for habit_key, habit_data in gt["habits"].items():
            if habit_key == planted_key:
                assert habit_data["planted"] is True
                assert habit_data["intensity"] == "medium"
                assert len(habit_data["trade_ids"]) > 0
                assert len(habit_data["entry_order_ids"]) > 0
                assert len(habit_data["exit_order_ids"]) > 0
                assert habit_data["injected_loss_inr"] > 0
            else:
                assert habit_data["planted"] is False
                assert habit_data["intensity"] is None
                assert habit_data["trade_ids"] == []
                assert habit_data["injected_loss_inr"] == 0.0


def test_ground_truth_order_ids_exist_in_data() -> None:
    """Verify all ground-truth order IDs exist in corresponding dataset CSV files."""
    for name in DATASET_SPECIFICATIONS:
        csv_path = Path(f"data/datasets/{name}.csv")
        gt_path = Path(f"data/ground_truth/{name}.json")

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            order_ids = {row["order_id"] for row in reader}

        with open(gt_path, encoding="utf-8") as f:
            gt = json.load(f)

        for habit_data in gt["habits"].values():
            if habit_data["planted"]:
                for oid in habit_data["entry_order_ids"]:
                    assert oid in order_ids, f"{oid} not in {csv_path.name}"
                for oid in habit_data["exit_order_ids"]:
                    assert oid in order_ids, f"{oid} not in {csv_path.name}"


def test_messy_dataset_ingest_warnings_match() -> None:
    """Verify messy.csv contains expected duplicate, missing price, and rejected orders."""
    csv_path = Path("data/datasets/messy.csv")
    gt_path = Path("data/ground_truth/messy.json")

    with open(gt_path, encoding="utf-8") as f:
        gt = json.load(f)

    expected = gt["expected_ingest_warnings"]

    with open(csv_path, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    # Count rejected
    rejected_count = sum(1 for r in reader if r["status"] == "REJECTED")
    assert rejected_count == expected["rejected"]

    # Count missing prices
    missing_price_count = sum(1 for r in reader if not r["price"])
    assert missing_price_count == expected["missing_price"]

    # Count duplicates
    row_strings = [tuple(r.values()) for r in reader]
    duplicates_count = len(row_strings) - len(set(row_strings))
    assert duplicates_count == expected["duplicates"]


def test_generate_all_determinism() -> None:
    """Verify running generate_all produces all 8 datasets."""
    results = generate_all()
    assert len(results) == 8
    for name in DATASET_SPECIFICATIONS:
        assert name in results
        csv_file, json_file = results[name]
        assert csv_file.exists()
        assert json_file.exists()
