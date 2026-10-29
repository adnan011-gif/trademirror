"""Unit and ground-truth integration tests for FIFO round-trip trade matching."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.models import Order
from app.pairing import pair_orders
from app.parsers.orders_csv import parse_orders

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _order(
    oid: str,
    dt_str: str,
    side: str,
    qty: int,
    price: float,
    symbol: str = "NIFTY24OCT25000CE",
    inst: str = "CE",
    strike: float = 25000.0,
    lot_size: int = 75,
    status: str = "COMPLETE",
) -> Order:
    """Helper to create domain Order objects for pairing tests."""
    return Order(
        order_id=oid,
        timestamp=datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S%z"),
        symbol=symbol,
        instrument_type=inst,
        strike=strike,
        expiry=date(2024, 10, 31),
        side=side,
        quantity=qty,
        lot_size=lot_size,
        price=price,
        status=status,
    )


def test_simple_round_trip() -> None:
    """Verify simple long round trip with hand-computed gross P&L."""
    orders = [
        _order("O1", "2024-10-01 09:20:00+0530", "BUY", 75, 100.0),
        _order("O2", "2024-10-01 09:40:00+0530", "SELL", 75, 140.0),
    ]
    res = pair_orders(orders)

    assert len(res.trades) == 1
    assert len(res.open_positions) == 0
    assert len(res.anomalies) == 0

    t = res.trades[0]
    assert t.trade_id == "P0001"
    assert t.direction == "LONG"
    assert t.quantity == 75
    assert t.entry_price == 100.0
    assert t.exit_price == 140.0
    assert t.gross_pnl == (140.0 - 100.0) * 75  # 3000.0
    assert t.hold_minutes == 20.0
    assert t.entry_order_id == "O1"
    assert t.exit_order_id == "O2"
    assert not t.is_partial_exit
    assert not t.is_add_on


def test_partial_exit() -> None:
    """Verify BUY 150, SELL 50, SELL 100 yields two trades; second is not partial."""
    orders = [
        _order("O1", "2024-10-01 09:20:00+0530", "BUY", 150, 100.0),
        _order("O2", "2024-10-01 09:35:00+0530", "SELL", 50, 120.0),
        _order("O3", "2024-10-01 09:50:00+0530", "SELL", 100, 130.0),
    ]
    res = pair_orders(orders)

    assert len(res.trades) == 2
    assert len(res.open_positions) == 0

    t1, t2 = res.trades
    # First trade: 50 qty partial exit of the 150 lot
    assert t1.quantity == 50
    assert t1.is_partial_exit is True
    assert t1.gross_pnl == (120.0 - 100.0) * 50  # 1000.0
    assert t1.entry_order_id == "O1"
    assert t1.exit_order_id == "O2"

    # Second trade: 100 qty closes remaining lot, not partial
    assert t2.quantity == 100
    assert t2.is_partial_exit is False
    assert t2.gross_pnl == (130.0 - 100.0) * 100  # 3000.0
    assert t2.entry_order_id == "O1"
    assert t2.exit_order_id == "O3"


def test_one_sell_closing_two_separate_lots_addon() -> None:
    """Verify one SELL closing two lots yields two trades with correct prices and is_add_on."""
    orders = [
        _order("O1", "2024-10-01 09:20:00+0530", "BUY", 75, 100.0),
        _order("O2", "2024-10-01 09:30:00+0530", "BUY", 75, 80.0),
        _order("O3", "2024-10-01 10:00:00+0530", "SELL", 150, 110.0),
    ]
    res = pair_orders(orders)

    assert len(res.trades) == 2
    assert len(res.open_positions) == 0

    t1, t2 = res.trades
    assert t1.quantity == 75
    assert t1.entry_price == 100.0
    assert t1.exit_price == 110.0
    assert t1.gross_pnl == (110.0 - 100.0) * 75  # 750.0
    assert t1.entry_order_id == "O1"
    assert t1.exit_order_id == "O3"
    assert t1.is_add_on is False

    assert t2.quantity == 75
    assert t2.entry_price == 80.0
    assert t2.exit_price == 110.0
    assert t2.gross_pnl == (110.0 - 80.0) * 75  # 2250.0
    assert t2.entry_order_id == "O2"
    assert t2.exit_order_id == "O3"
    assert t2.is_add_on is True


def test_short_then_cover() -> None:
    """Verify short sell followed by buy cover calculates gross P&L correctly."""
    orders = [
        _order("O1", "2024-10-01 09:20:00+0530", "SELL", 75, 150.0),
        _order("O2", "2024-10-01 09:40:00+0530", "BUY", 75, 110.0),
    ]
    res = pair_orders(orders)

    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.direction == "SHORT"
    assert t.entry_price == 150.0
    assert t.exit_price == 110.0
    assert t.gross_pnl == (150.0 - 110.0) * 75  # 3000.0


def test_position_flip() -> None:
    """Verify long 100 then SELL 250 closes long (100) and opens short (150)."""
    orders = [
        _order("O1", "2024-10-01 09:20:00+0530", "BUY", 100, 100.0),
        _order("O2", "2024-10-01 09:40:00+0530", "SELL", 250, 120.0),
    ]
    res = pair_orders(orders)

    # Closed trade for the long position
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.direction == "LONG"
    assert t.quantity == 100
    assert t.gross_pnl == (120.0 - 100.0) * 100

    # Remaining 150 opens short position
    assert len(res.open_positions) == 1
    open_pos = res.open_positions[0]
    assert open_pos.direction == "SHORT"
    assert open_pos.quantity == 150
    assert open_pos.entry_price == 120.0
    assert open_pos.entry_order_id == "O2"
    assert len(res.anomalies) == 1


def test_open_position_at_end_reported_in_anomalies() -> None:
    """Verify unclosed order is absent from trades and recorded in open_positions & anomalies."""
    orders = [_order("O1", "2024-10-01 09:20:00+0530", "BUY", 75, 100.0)]
    res = pair_orders(orders)

    assert len(res.trades) == 0
    assert len(res.open_positions) == 1
    assert res.open_positions[0].quantity == 75
    assert len(res.anomalies) == 1
    assert "Open position at end of period" in res.anomalies[0]


def test_interleaved_scrips_pair_independently() -> None:
    """Verify multiple instruments interleaved in time pair independently."""
    orders = [
        _order("O1", "2024-10-01 09:20:00+0530", "BUY", 75, 100.0, symbol="NIFTY_A", strike=25000),
        _order("O2", "2024-10-01 09:22:00+0530", "BUY", 35, 200.0, symbol="BANK_B", strike=51000),
        _order("O3", "2024-10-01 09:25:00+0530", "BUY", 75, 150.0, symbol="NIFTY_C", strike=25200),
        _order("O4", "2024-10-01 09:40:00+0530", "SELL", 35, 250.0, symbol="BANK_B", strike=51000),
        _order("O5", "2024-10-01 09:45:00+0530", "SELL", 75, 90.0, symbol="NIFTY_A", strike=25000),
        _order("O6", "2024-10-01 09:50:00+0530", "SELL", 75, 180.0, symbol="NIFTY_C", strike=25200),
    ]
    res = pair_orders(orders)

    assert len(res.trades) == 3
    assert len(res.open_positions) == 0

    trade_symbols = {t.symbol: t for t in res.trades}
    assert trade_symbols["BANK_B"].gross_pnl == (250.0 - 200.0) * 35
    assert trade_symbols["NIFTY_A"].gross_pnl == (90.0 - 100.0) * 75
    assert trade_symbols["NIFTY_C"].gross_pnl == (180.0 - 150.0) * 75


def test_determinism_and_unsorted_input() -> None:
    """Verify pairing is deterministic and produces identical output regardless of order."""
    orders = [
        _order("O1", "2024-10-01 09:20:00+0530", "BUY", 75, 100.0),
        _order("O2", "2024-10-01 09:40:00+0530", "SELL", 75, 120.0),
        _order("O3", "2024-10-01 10:00:00+0530", "BUY", 75, 150.0),
        _order("O4", "2024-10-01 10:30:00+0530", "SELL", 75, 130.0),
    ]
    res1 = pair_orders(orders)

    # Provide shuffled list
    shuffled = [orders[3], orders[0], orders[2], orders[1]]
    res2 = pair_orders(shuffled)

    assert len(res1.trades) == len(res2.trades)
    for t1, t2 in zip(res1.trades, res2.trades, strict=True):
        assert t1 == t2


@pytest.mark.parametrize(
    "dataset_name",
    [
        "clean",
        "single_holding_losers",
        "single_revenge_trading",
        "single_overtrading",
        "single_oversizing",
        "single_averaging_down",
        "mixed",
        "messy",
    ],
)
def test_ground_truth_datasets_invariants_and_coverage(dataset_name: str) -> None:
    """Verify pairing on all benchmark datasets satisfies invariants 1-4 and coverage."""
    csv_path = Path(f"data/datasets/{dataset_name}.csv")
    gt_path = Path(f"data/ground_truth/{dataset_name}.json")

    assert csv_path.exists()
    assert gt_path.exists()

    parsed = parse_orders(csv_path)
    res = pair_orders(parsed.orders)

    # Invariant: open_positions must be empty (generator closes everything)
    assert len(res.open_positions) == 0, f"{dataset_name} had open positions: {res.open_positions}"

    # Invariant 1: Quantity conservation per key
    opened_by_key: dict[tuple[str, str, float, date], int] = {}
    closed_by_key: dict[tuple[str, str, float, date], int] = {}

    for o in parsed.orders:
        k = (o.symbol, o.instrument_type, o.strike or 0.0, o.expiry or date.min)
        opened_by_key[k] = opened_by_key.get(k, 0) + o.quantity

    for t in res.trades:
        k = (t.symbol, t.instrument_type, t.strike, t.expiry)
        # Each trade matches 2 * quantity of orders (one entry slice + one exit slice)
        closed_by_key[k] = closed_by_key.get(k, 0) + (t.quantity * 2)

    for k, total_qty in opened_by_key.items():
        closed_qty = closed_by_key.get(k, 0)
        assert closed_qty == total_qty, f"Qty mismatch for {k}: {closed_qty} != {total_qty}"

    # Invariant 2: Cash-flow identity
    # Sum(trade.gross_pnl) == sum(sell_price * qty - buy_price * qty)
    total_trade_pnl = sum(t.gross_pnl for t in res.trades)
    cashflow_pnl = sum(
        (t.exit_price - t.entry_price) * t.quantity if t.direction == "LONG"
        else (t.entry_price - t.exit_price) * t.quantity
        for t in res.trades
    )
    assert abs(total_trade_pnl - cashflow_pnl) < 1e-4

    # Invariant 3 & 4: hold_minutes >= 0, exit_time >= entry_time, quantity > 0
    for t in res.trades:
        assert t.hold_minutes >= 0.0
        assert t.exit_time >= t.entry_time
        assert t.quantity > 0

    # Ground truth order id coverage
    with open(gt_path, encoding="utf-8") as f:
        gt = json.load(f)

    trade_entry_oids = {t.entry_order_id for t in res.trades}
    trade_exit_oids = {t.exit_order_id for t in res.trades}

    for habit_name, habit_data in gt["habits"].items():
        if habit_data["planted"]:
            for e_oid in habit_data["entry_order_ids"]:
                assert e_oid in trade_entry_oids, (
                    f"Dataset {dataset_name}, habit {habit_name}: entry order {e_oid} missing"
                )
            for x_oid in habit_data["exit_order_ids"]:
                assert x_oid in trade_exit_oids, (
                    f"Dataset {dataset_name}, habit {habit_name}: exit order {x_oid} missing"
                )

    # Clean dataset specific assertion
    if dataset_name == "clean":
        # In clean, every trade is 1 buy and 1 sell, so paired trades == raw orders // 2
        assert len(res.trades) == len(parsed.orders) // 2

    # Single averaging down specific assertion
    if dataset_name == "single_averaging_down":
        gt_addon_oids = set(gt["habits"]["averaging_down"]["entry_order_ids"])
        paired_addon_oids = {t.entry_order_id for t in res.trades if t.is_add_on}
        assert gt_addon_oids == paired_addon_oids, (
            f"Add-on entry order IDs mismatch: {gt_addon_oids} != {paired_addon_oids}"
        )
