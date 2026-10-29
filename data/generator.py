"""Synthetic order history and ground-truth generator for TradeMirror.

Responsibility:
Generates deterministic synthetic option trading data for retail Indian F&O traders
(NIFTY and BANKNIFTY long-only CE/PE) across one fixed trading month.
Supports clean baseline generation and controlled injection of 5 specific behavioral habits:
holding_losers, revenge_trading, overtrading, oversizing, and averaging_down.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Literal

# Named constants for lot sizes
NIFTY_LOT_SIZE = 75
BANKNIFTY_LOT_SIZE = 35

# Named constants for clean baseline constraints
BASELINE_MIN_DAILY_TRADES = 3
BASELINE_MAX_DAILY_TRADES = 6
BASELINE_MAX_DAILY_TO_MEDIAN_RATIO = 1.5
BASELINE_DEFAULT_LOTS = 1
BASELINE_MIN_LOTS = 1
BASELINE_MAX_LOTS = 2
BASELINE_MAX_SIZE_JUMP_RATIO = 1.5
BASELINE_MIN_POST_LOSS_ENTRY_MINUTES = 45
BASELINE_WIN_HOLD_MINUTES_RANGE = (12, 32)
BASELINE_LOSS_HOLD_MINUTES_RANGE = (12, 32)

# Trading session constants
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)
TRADING_MONTH_YEAR = 2024
TRADING_MONTH = 10  # October 2024

CANONICAL_COLUMNS = [
    "order_id",
    "timestamp",
    "symbol",
    "instrument_type",
    "strike",
    "expiry",
    "side",
    "quantity",
    "lot_size",
    "price",
    "status",
]

Intensity = Literal["low", "medium", "high"]


@dataclass
class SyntheticOrder:
    """Internal representation of a generated order."""

    order_id: str
    timestamp: datetime
    symbol: str
    instrument_type: str
    strike: float
    expiry: date
    side: str
    quantity: int
    lot_size: int
    price: float | None
    status: str

    def to_csv_dict(self) -> dict[str, str]:
        """Convert order to dictionary with canonical CSV string formatting."""
        return {
            "order_id": self.order_id,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S%z"),
            "symbol": self.symbol,
            "instrument_type": self.instrument_type,
            "strike": f"{self.strike:.1f}",
            "expiry": self.expiry.isoformat(),
            "side": self.side,
            "quantity": str(self.quantity),
            "lot_size": str(self.lot_size),
            "price": f"{self.price:.2f}" if self.price is not None else "",
            "status": self.status,
        }


@dataclass
class SyntheticTrade:
    """Internal representation of a round-trip synthetic trade."""

    trade_id: str
    symbol: str
    instrument_type: str
    strike: float
    expiry: date
    lot_size: int
    lots: int
    quantity: int
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    pnl_inr: float
    entry_order_ids: list[str] = field(default_factory=list)
    exit_order_ids: list[str] = field(default_factory=list)
    addon_orders: list[SyntheticOrder] = field(default_factory=list)


def get_october_2024_weekdays() -> list[date]:
    """Return all weekday trading dates in October 2024 (excluding weekends)."""
    days: list[date] = []
    # 2024-10-01 to 2024-10-31
    for d in range(1, 32):
        dt = date(TRADING_MONTH_YEAR, TRADING_MONTH, d)
        if dt.weekday() < 5:  # Monday to Friday
            days.append(dt)
    return days


class SyntheticGenerator:
    """Deterministic generator for synthetic Indian F&O order books and ground truth."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.order_counter = 1
        self.trade_counter = 1

    def _next_order_id(self) -> str:
        oid = f"ORD{self.order_counter:05d}"
        self.order_counter += 1
        return oid

    def _next_trade_id(self) -> str:
        tid = f"T{self.trade_counter:04d}"
        self.trade_counter += 1
        return tid

    def _generate_clean_trades(self, trading_days: list[date]) -> list[SyntheticTrade]:
        """Generate baseline trades strictly conforming to clean baseline constraints."""
        trades: list[SyntheticTrade] = []

        expiry_date = date(2024, 10, 31)

        for day in trading_days:
            # 3 to 6 trades per day
            daily_count = self.rng.randint(BASELINE_MIN_DAILY_TRADES, BASELINE_MAX_DAILY_TRADES)

            # Available daily window: 09:20 to 15:15
            current_time = datetime(
                day.year, day.month, day.day, 9, 20, 0, tzinfo=IST
            )

            for _ in range(daily_count):
                if current_time.time() >= time(14, 50):
                    break

                # Underlying selection: NIFTY or BANKNIFTY
                if self.rng.random() < 0.6:
                    underlying = "NIFTY"
                    lot_size = NIFTY_LOT_SIZE
                    strike = float(self.rng.choice([24800, 24900, 25000, 25100, 25200]))
                else:
                    underlying = "BANKNIFTY"
                    lot_size = BANKNIFTY_LOT_SIZE
                    strike = float(self.rng.choice([50800, 51000, 51200, 51500]))

                inst_type = self.rng.choice(["CE", "PE"])
                exp_code = expiry_date.strftime("%y%b").upper()
                symbol = f"{underlying}{exp_code}{int(strike)}{inst_type}"

                # Baseline lots: fixed at 1 lot (no size jumps above 1.5x median)
                lots = BASELINE_DEFAULT_LOTS
                quantity = lots * lot_size

                # Entry premium 40 - 250 INR
                entry_price = round(self.rng.uniform(40.0, 250.0), 2)

                # Return drawn to achieve ~45-55% win rate
                is_win = self.rng.random() < 0.50
                if is_win:
                    return_pct = self.rng.uniform(0.10, 0.45)
                    # Hold times drawn from identical distribution
                    hold_minutes = self.rng.randint(*BASELINE_WIN_HOLD_MINUTES_RANGE)
                else:
                    return_pct = -self.rng.uniform(0.10, 0.40)
                    hold_minutes = self.rng.randint(*BASELINE_LOSS_HOLD_MINUTES_RANGE)

                exit_price = max(1.0, round(entry_price * (1.0 + return_pct), 2))
                pnl = round((exit_price - entry_price) * quantity, 2)

                entry_time = current_time
                exit_time = entry_time + timedelta(minutes=hold_minutes)

                # Don't let trade exceed market close
                market_close = datetime(day.year, day.month, day.day, 15, 25, 0, tzinfo=IST)
                if exit_time > market_close:
                    exit_time = market_close

                tid = self._next_trade_id()
                entry_oid = self._next_order_id()
                exit_oid = self._next_order_id()

                trade = SyntheticTrade(
                    trade_id=tid,
                    symbol=symbol,
                    instrument_type=inst_type,
                    strike=strike,
                    expiry=expiry_date,
                    lot_size=lot_size,
                    lots=lots,
                    quantity=quantity,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_inr=pnl,
                    entry_order_ids=[entry_oid],
                    exit_order_ids=[exit_oid],
                )
                trades.append(trade)

                # Time between trades:
                # If trade was a loss, at least 45 minutes between loss and next entry!
                # If trade was a win, gap can be 15-30 minutes.
                if is_win:
                    gap_minutes = self.rng.randint(15, 30)
                else:
                    gap_minutes = self.rng.randint(BASELINE_MIN_POST_LOSS_ENTRY_MINUTES, 60)

                current_time = exit_time + timedelta(minutes=gap_minutes)

        return trades

    def generate_dataset(
        self,
        name: str,
        habits_config: dict[str, Intensity | None] | None = None,
        messy: bool = False,
    ) -> tuple[list[SyntheticOrder], dict[str, Any]]:
        """Generate a complete order book dataset and matching ground-truth JSON."""
        weekdays = get_october_2024_weekdays()
        trades = self._generate_clean_trades(weekdays)

        if habits_config is None:
            habits_config = {}

        # Ground truth structure
        ground_truth: dict[str, Any] = {
            "dataset": name,
            "seed": self.seed,
            "habits": {
                "holding_losers": {
                    "planted": False,
                    "intensity": None,
                    "trade_ids": [],
                    "entry_order_ids": [],
                    "exit_order_ids": [],
                    "injected_loss_inr": 0.0,
                },
                "revenge_trading": {
                    "planted": False,
                    "intensity": None,
                    "trade_ids": [],
                    "entry_order_ids": [],
                    "exit_order_ids": [],
                    "injected_loss_inr": 0.0,
                },
                "overtrading": {
                    "planted": False,
                    "intensity": None,
                    "trade_ids": [],
                    "entry_order_ids": [],
                    "exit_order_ids": [],
                    "injected_loss_inr": 0.0,
                },
                "oversizing": {
                    "planted": False,
                    "intensity": None,
                    "trade_ids": [],
                    "entry_order_ids": [],
                    "exit_order_ids": [],
                    "injected_loss_inr": 0.0,
                },
                "averaging_down": {
                    "planted": False,
                    "intensity": None,
                    "trade_ids": [],
                    "entry_order_ids": [],
                    "exit_order_ids": [],
                    "injected_loss_inr": 0.0,
                },
            },
            "expected_ingest_warnings": {
                "duplicates": 0,
                "missing_price": 0,
                "rejected": 0,
            },
        }

        # Calculate baseline median winner hold time
        winner_hold_times = [
            (t.exit_time - t.entry_time).total_seconds() / 60.0
            for t in trades
            if t.pnl_inr > 0
        ]
        winner_hold_times.sort()
        median_winner_hold = (
            winner_hold_times[len(winner_hold_times) // 2] if winner_hold_times else 20.0
        )

        # 1. Plant holding_losers: affected losers held > 2x median winner hold time
        if habits_config.get("holding_losers"):
            intensity = habits_config["holding_losers"]
            ratio = {"low": 0.15, "medium": 0.35, "high": 0.60}[intensity]
            losing_trades = [t for t in trades if t.pnl_inr < 0]
            count_to_plant = max(1, int(len(losing_trades) * ratio))
            sample_count = min(count_to_plant, len(losing_trades))
            selected_losers = self.rng.sample(losing_trades, sample_count)

            flagged_tids = []
            flagged_entry_oids = []
            flagged_exit_oids = []
            extra_loss = 0.0

            for t in selected_losers:
                # Extend hold time to > 2x median winner hold
                new_hold = round(median_winner_hold * self.rng.uniform(2.3, 3.5))
                new_exit_time = t.entry_time + timedelta(minutes=new_hold)
                market_close = datetime(
                    t.entry_time.year, t.entry_time.month, t.entry_time.day, 15, 25, 0, tzinfo=IST
                )
                if new_exit_time > market_close:
                    new_exit_time = market_close

                # Additional price decay due to holding on to loser
                old_exit_price = t.exit_price
                new_exit_price = max(0.5, round(old_exit_price * self.rng.uniform(0.40, 0.70), 2))
                added_loss = round((old_exit_price - new_exit_price) * t.quantity, 2)

                t.exit_time = new_exit_time
                t.exit_price = new_exit_price
                t.pnl_inr = round((new_exit_price - t.entry_price) * t.quantity, 2)

                extra_loss += added_loss
                flagged_tids.append(t.trade_id)
                flagged_entry_oids.extend(t.entry_order_ids)
                flagged_exit_oids.extend(t.exit_order_ids)

            ground_truth["habits"]["holding_losers"] = {
                "planted": True,
                "intensity": intensity,
                "trade_ids": flagged_tids,
                "entry_order_ids": flagged_entry_oids,
                "exit_order_ids": flagged_exit_oids,
                "injected_loss_inr": round(extra_loss, 2),
            }

        # 2. Plant revenge_trading: after a losing close, re-enter within 15 min with size >= 1.5x
        if habits_config.get("revenge_trading"):
            intensity = habits_config["revenge_trading"]
            ratio = {"low": 0.15, "medium": 0.30, "high": 0.50}[intensity]
            # Find trades following a loss
            candidates: list[int] = []
            for i in range(1, len(trades)):
                prev = trades[i - 1]
                curr = trades[i]
                if prev.pnl_inr < 0 and prev.exit_time.date() == curr.entry_time.date():
                    candidates.append(i)

            count = max(1, int(len(candidates) * ratio))
            selected_indices = self.rng.sample(candidates, min(count, len(candidates)))

            flagged_tids = []
            flagged_entry_oids = []
            flagged_exit_oids = []
            extra_loss = 0.0

            for idx in selected_indices:
                prev = trades[idx - 1]
                curr = trades[idx]

                # Move entry to within 2 to 12 minutes of prev exit
                gap = timedelta(minutes=self.rng.randint(2, 12))
                new_entry = prev.exit_time + gap
                curr_duration = curr.exit_time - curr.entry_time
                curr.entry_time = new_entry
                curr.exit_time = new_entry + curr_duration

                # Increase size to >= 1.5x of prev quantity (e.g. 2x lots)
                curr.lots = max(curr.lots + 1, int(prev.lots * 1.5 + 0.5))
                curr.quantity = curr.lots * curr.lot_size

                # Revenge trade is made to suffer a loss
                loss_pct = self.rng.uniform(0.20, 0.50)
                curr.exit_price = max(1.0, round(curr.entry_price * (1.0 - loss_pct), 2))
                curr.pnl_inr = round((curr.exit_price - curr.entry_price) * curr.quantity, 2)

                extra_loss += abs(curr.pnl_inr)
                flagged_tids.append(curr.trade_id)
                flagged_entry_oids.extend(curr.entry_order_ids)
                flagged_exit_oids.extend(curr.exit_order_ids)

            ground_truth["habits"]["revenge_trading"] = {
                "planted": True,
                "intensity": intensity,
                "trade_ids": flagged_tids,
                "entry_order_ids": flagged_entry_oids,
                "exit_order_ids": flagged_exit_oids,
                "injected_loss_inr": round(extra_loss, 2),
            }

        # 3. Plant overtrading: some days get > 2x the median daily count; mark excess trades
        if habits_config.get("overtrading"):
            intensity = habits_config["overtrading"]
            target_days_count = {"low": 1, "medium": 3, "high": 5}[intensity]

            # Pick target days
            days_by_date: dict[date, list[SyntheticTrade]] = {}
            for t in trades:
                days_by_date.setdefault(t.entry_time.date(), []).append(t)

            candidate_days = [d for d, tlist in days_by_date.items() if len(tlist) >= 3]
            sample_days = min(target_days_count, len(candidate_days))
            selected_days = self.rng.sample(candidate_days, sample_days)

            flagged_tids = []
            flagged_entry_oids = []
            flagged_exit_oids = []
            extra_loss = 0.0

            for d in selected_days:
                existing = days_by_date[d]
                median_daily = 4
                excess_needed = max(4, (median_daily * 2 + 1) - len(existing))

                last_exit = existing[-1].exit_time
                for _ in range(excess_needed):
                    if last_exit.time() >= time(15, 10):
                        break
                    entry_t = last_exit + timedelta(minutes=self.rng.randint(3, 8))
                    exit_t = entry_t + timedelta(minutes=self.rng.randint(5, 12))
                    if exit_t.time() > time(15, 25):
                        break

                    lot_size = NIFTY_LOT_SIZE
                    lots = 1
                    quantity = lots * lot_size
                    entry_p = round(self.rng.uniform(60.0, 180.0), 2)
                    # Overtrading excess trades tend to chop and lose
                    exit_p = max(1.0, round(entry_p * (1.0 - self.rng.uniform(0.10, 0.35)), 2))
                    pnl = round((exit_p - entry_p) * quantity, 2)

                    tid = self._next_trade_id()
                    e_oid = self._next_order_id()
                    x_oid = self._next_order_id()

                    excess_trade = SyntheticTrade(
                        trade_id=tid,
                        symbol="NIFTY24OCT25000CE",
                        instrument_type="CE",
                        strike=25000.0,
                        expiry=date(2024, 10, 31),
                        lot_size=lot_size,
                        lots=lots,
                        quantity=quantity,
                        entry_time=entry_t,
                        exit_time=exit_t,
                        entry_price=entry_p,
                        exit_price=exit_p,
                        pnl_inr=pnl,
                        entry_order_ids=[e_oid],
                        exit_order_ids=[x_oid],
                    )
                    trades.append(excess_trade)
                    days_by_date[d].append(excess_trade)
                    last_exit = exit_t

                    extra_loss += abs(pnl) if pnl < 0 else 0.0
                    flagged_tids.append(tid)
                    flagged_entry_oids.append(e_oid)
                    flagged_exit_oids.append(x_oid)

            ground_truth["habits"]["overtrading"] = {
                "planted": True,
                "intensity": intensity,
                "trade_ids": flagged_tids,
                "entry_order_ids": flagged_entry_oids,
                "exit_order_ids": flagged_exit_oids,
                "injected_loss_inr": round(extra_loss, 2),
            }

        # 4. Plant oversizing: after 2+ win or loss streak, next trade quantity > 2x median
        # Must not overlap with revenge trading (entry gap >= 45 min or follows win streak)
        if habits_config.get("oversizing"):
            intensity = habits_config["oversizing"]
            ratio = {"low": 0.20, "medium": 0.40, "high": 0.70}[intensity]

            # Find streak >= 2 opportunities
            opportunities: list[int] = []
            streak = 0
            prev_win = None
            for i in range(len(trades)):
                is_win = trades[i].pnl_inr > 0
                if prev_win is None:
                    streak = 1
                elif is_win == prev_win:
                    streak += 1
                else:
                    streak = 1
                prev_win = is_win

                if streak >= 2 and i + 1 < len(trades):
                    next_t = trades[i + 1]
                    curr_t = trades[i]
                    # Ensure no overlap with revenge trading
                    gap = (next_t.entry_time - curr_t.exit_time).total_seconds() / 60.0
                    if gap >= 30.0 or is_win:
                        opportunities.append(i + 1)

            count = max(1, int(len(opportunities) * ratio))
            selected = self.rng.sample(opportunities, min(count, len(opportunities)))

            flagged_tids = []
            flagged_entry_oids = []
            flagged_exit_oids = []
            extra_loss = 0.0

            for idx in selected:
                t = trades[idx]
                old_lots = t.lots
                # Median lots is ~1. Set oversized lots > 2x median (e.g. 4 lots)
                new_lots = self.rng.choice([3, 4])
                t.lots = new_lots
                t.quantity = new_lots * t.lot_size
                # Compute loss impact on excess quantity
                loss_pct = self.rng.uniform(0.15, 0.45)
                t.exit_price = max(1.0, round(t.entry_price * (1.0 - loss_pct), 2))
                t.pnl_inr = round((t.exit_price - t.entry_price) * t.quantity, 2)
                excess_qty = (new_lots - old_lots) * t.lot_size
                excess_loss = round((t.entry_price - t.exit_price) * excess_qty, 2)

                extra_loss += excess_loss
                flagged_tids.append(t.trade_id)
                flagged_entry_oids.extend(t.entry_order_ids)
                flagged_exit_oids.extend(t.exit_order_ids)

            ground_truth["habits"]["oversizing"] = {
                "planted": True,
                "intensity": intensity,
                "trade_ids": flagged_tids,
                "entry_order_ids": flagged_entry_oids,
                "exit_order_ids": flagged_exit_oids,
                "injected_loss_inr": round(extra_loss, 2),
            }

        # 5. Plant averaging_down: add a second BUY in same scrip while open position is below entry
        if habits_config.get("averaging_down"):
            intensity = habits_config["averaging_down"]
            ratio = {"low": 0.15, "medium": 0.35, "high": 0.60}[intensity]

            losing_trades = [t for t in trades if t.pnl_inr < 0 and len(t.addon_orders) == 0]
            count = max(1, int(len(losing_trades) * ratio))
            selected = self.rng.sample(losing_trades, min(count, len(losing_trades)))

            flagged_tids = []
            flagged_entry_oids = []
            flagged_exit_oids = []
            extra_loss = 0.0

            for t in selected:
                # Add-on entry happens halfway into trade duration
                mid_time = t.entry_time + (t.exit_time - t.entry_time) / 2
                # Lower price for averaging down
                addon_price = round(t.entry_price * self.rng.uniform(0.75, 0.90), 2)
                addon_lots = t.lots
                addon_qty = addon_lots * t.lot_size
                addon_oid = self._next_order_id()

                addon_order = SyntheticOrder(
                    order_id=addon_oid,
                    timestamp=mid_time,
                    symbol=t.symbol,
                    instrument_type=t.instrument_type,
                    strike=t.strike,
                    expiry=t.expiry,
                    side="BUY",
                    quantity=addon_qty,
                    lot_size=t.lot_size,
                    price=addon_price,
                    status="COMPLETE",
                )
                t.addon_orders.append(addon_order)

                # Total exit quantity will be initial quantity + addon_qty
                addon_loss = round((addon_price - t.exit_price) * addon_qty, 2)
                extra_loss += max(0.0, addon_loss)

                flagged_tids.append(t.trade_id)
                flagged_entry_oids.append(addon_oid)
                flagged_exit_oids.extend(t.exit_order_ids)

            ground_truth["habits"]["averaging_down"] = {
                "planted": True,
                "intensity": intensity,
                "trade_ids": flagged_tids,
                "entry_order_ids": flagged_entry_oids,
                "exit_order_ids": flagged_exit_oids,
                "injected_loss_inr": round(extra_loss, 2),
            }

        # Emit ORDERS from TRADES
        orders: list[SyntheticOrder] = []
        for t in trades:
            # Entry order
            orders.append(
                SyntheticOrder(
                    order_id=t.entry_order_ids[0],
                    timestamp=t.entry_time,
                    symbol=t.symbol,
                    instrument_type=t.instrument_type,
                    strike=t.strike,
                    expiry=t.expiry,
                    side="BUY",
                    quantity=t.quantity,
                    lot_size=t.lot_size,
                    price=t.entry_price,
                    status="COMPLETE",
                )
            )
            # Add-on orders (if any from averaging down)
            for addon in t.addon_orders:
                orders.append(addon)

            # Exit order (sells total accumulated quantity)
            total_qty = t.quantity + sum(a.quantity for a in t.addon_orders)
            orders.append(
                SyntheticOrder(
                    order_id=t.exit_order_ids[0],
                    timestamp=t.exit_time,
                    symbol=t.symbol,
                    instrument_type=t.instrument_type,
                    strike=t.strike,
                    expiry=t.expiry,
                    side="SELL",
                    quantity=total_qty,
                    lot_size=t.lot_size,
                    price=t.exit_price,
                    status="COMPLETE",
                )
            )

        # Sort orders strictly by timestamp
        orders.sort(key=lambda o: o.timestamp)

        # If messy dataset requested, inject messy anomalies
        if messy:
            orders = self._inject_messy_anomalies(orders, ground_truth)

        return orders, ground_truth

    def _inject_messy_anomalies(
        self, orders: list[SyntheticOrder], ground_truth: dict[str, Any]
    ) -> list[SyntheticOrder]:
        """Inject duplicates, missing prices, rejected orders, and timestamp shuffles."""
        messy_orders = list(orders)

        # 1. Exact duplicate rows (e.g., 3 duplicates)
        dup_count = 3
        dup_candidates = self.rng.sample(orders, dup_count)
        for dup in dup_candidates:
            # Clone identical order
            messy_orders.append(
                SyntheticOrder(
                    order_id=dup.order_id,
                    timestamp=dup.timestamp,
                    symbol=dup.symbol,
                    instrument_type=dup.instrument_type,
                    strike=dup.strike,
                    expiry=dup.expiry,
                    side=dup.side,
                    quantity=dup.quantity,
                    lot_size=dup.lot_size,
                    price=dup.price,
                    status=dup.status,
                )
            )

        # 2. Rows with missing price (price = None) (e.g. 2 orders)
        missing_count = 2
        for _ in range(missing_count):
            base_order = self.rng.choice(orders)
            mis_time = base_order.timestamp + timedelta(seconds=self.rng.randint(1, 10))
            mis_order = SyntheticOrder(
                order_id=self._next_order_id(),
                timestamp=mis_time,
                symbol=base_order.symbol,
                instrument_type=base_order.instrument_type,
                strike=base_order.strike,
                expiry=base_order.expiry,
                side=base_order.side,
                quantity=base_order.quantity,
                lot_size=base_order.lot_size,
                price=None,
                status="COMPLETE",
            )
            messy_orders.append(mis_order)

        # 3. Status = REJECTED rows (e.g., 4 rejected orders)
        rejected_count = 4
        for _ in range(rejected_count):
            base_order = self.rng.choice(orders)
            rej_time = base_order.timestamp + timedelta(seconds=self.rng.randint(1, 10))
            rej_order = SyntheticOrder(
                order_id=self._next_order_id(),
                timestamp=rej_time,
                symbol=base_order.symbol,
                instrument_type=base_order.instrument_type,
                strike=base_order.strike,
                expiry=base_order.expiry,
                side=base_order.side,
                quantity=base_order.quantity,
                lot_size=base_order.lot_size,
                price=base_order.price,
                status="REJECTED",
            )
            messy_orders.append(rej_order)

        # 4. Shuffle timestamp order
        self.rng.shuffle(messy_orders)

        ground_truth["expected_ingest_warnings"] = {
            "duplicates": dup_count,
            "missing_price": missing_count,
            "rejected": rejected_count,
        }

        return messy_orders


DATASET_SPECIFICATIONS: dict[str, dict[str, Any]] = {
    "clean": {"seed": 101, "habits": {}, "messy": False},
    "single_holding_losers": {
        "seed": 102,
        "habits": {"holding_losers": "medium"},
        "messy": False,
    },
    "single_revenge_trading": {
        "seed": 103,
        "habits": {"revenge_trading": "medium"},
        "messy": False,
    },
    "single_overtrading": {
        "seed": 104,
        "habits": {"overtrading": "medium"},
        "messy": False,
    },
    "single_oversizing": {
        "seed": 105,
        "habits": {"oversizing": "medium"},
        "messy": False,
    },
    "single_averaging_down": {
        "seed": 106,
        "habits": {"averaging_down": "medium"},
        "messy": False,
    },
    "mixed": {
        "seed": 107,
        "habits": {
            "holding_losers": "high",
            "revenge_trading": "medium",
            "overtrading": "low",
        },
        "messy": False,
    },
    "messy": {
        "seed": 108,
        "habits": {
            "holding_losers": "high",
            "revenge_trading": "medium",
            "overtrading": "low",
        },
        "messy": True,
    },
}


def generate_dataset_in_memory(
    seed: int,
    habits_config: dict[str, Intensity | None] | None = None,
    messy: bool = False,
    name: str = "in_memory",
) -> tuple[str, dict[str, Any]]:
    """Generate in-memory CSV text and ground truth for testing/evaluations."""
    gen = SyntheticGenerator(seed=seed)
    orders, gt = gen.generate_dataset(name=name, habits_config=habits_config, messy=messy)
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=CANONICAL_COLUMNS)
    writer.writeheader()
    for o in orders:
        writer.writerow(o.to_csv_dict())
    return out.getvalue(), gt


def write_dataset_files(
    name: str,
    orders: list[SyntheticOrder],
    ground_truth: dict[str, Any],
    datasets_dir: Path,
    ground_truth_dir: Path,
) -> tuple[Path, Path]:
    """Write orders CSV and ground-truth JSON to respective directories."""
    datasets_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_dir.mkdir(parents=True, exist_ok=True)

    csv_path = datasets_dir / f"{name}.csv"
    json_path = ground_truth_dir / f"{name}.json"

    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        for order in orders:
            writer.writerow(order.to_csv_dict())

    with open(json_path, mode="w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2)

    return csv_path, json_path


def generate_all(
    datasets_dir: Path | None = None, ground_truth_dir: Path | None = None
) -> dict[str, tuple[Path, Path]]:
    """Regenerate all synthetic benchmark datasets with byte-identical determinism."""
    base_dir = Path(__file__).resolve().parent
    d_dir = datasets_dir or (base_dir / "datasets")
    gt_dir = ground_truth_dir or (base_dir / "ground_truth")

    results: dict[str, tuple[Path, Path]] = {}

    for name, spec in DATASET_SPECIFICATIONS.items():
        gen = SyntheticGenerator(seed=spec["seed"])
        orders, gt = gen.generate_dataset(
            name=name,
            habits_config=spec["habits"],
            messy=spec["messy"],
        )
        csv_file, json_file = write_dataset_files(name, orders, gt, d_dir, gt_dir)
        results[name] = (csv_file, json_file)

    return results


def main() -> None:
    """CLI entrypoint for data generation."""
    parser = argparse.ArgumentParser(description="Synthetic order data generator")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all benchmark datasets and ground truth files",
    )
    args = parser.parse_args()

    if args.all:
        generated = generate_all()
        for name, (csv_p, json_p) in generated.items():
            print(f"Generated {name}: {csv_p.name}, {json_p.name}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
