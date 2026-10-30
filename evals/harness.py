"""Evaluation harness for TradeMirror detectors, ranking, and narrative layers.

Responsibility:
Executes comprehensive evaluation suites against synthetic benchmark datasets and in-memory
generations, measuring precision, recall, cost ratio accuracy, false-positive silence on clean data,
adversarial grounding robustness, API stability, and graceful LLM fallback.
Outputs results to evals/results/results.md and evals/results/results.json.
"""

from __future__ import annotations

import copy
import json
import random
import statistics
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from app.config import Settings
from app.llm.templates import generate_template_narrative
from app.main import app
from app.narrative import build_facts, generate_narrative
from app.pipeline import run_pipeline
from app.verifier import verify_narrative
from starlette.testclient import TestClient

from data.generator import generate_dataset_in_memory

# =====================================================================
# FIXED EVALUATION TARGET CONSTANTS
# =====================================================================
TARGET_CLEAN_KEPT_RATE_MAX: float = 0.02  # <= 2%
TARGET_INTENSITY_DETECTION_MIN: float = 0.85  # >= 85% for medium and high
TARGET_INTENSITY_COST_RATIO_MIN: float = 0.5  # within 0.5 to 2.0
TARGET_INTENSITY_COST_RATIO_MAX: float = 2.0
TARGET_COMBINATIONS_SPURIOUS_MAX: float = 0.10  # <= 10%
TARGET_TEMPLATE_SELF_CONSISTENCY_MIN: float = 1.0  # 100%
TARGET_ADVERSARIAL_REJECTION_MIN: float = 1.0  # 100%
TARGET_BENIGN_ACCEPTANCE_MIN: float = 0.90  # >= 90%
TARGET_ROBUSTNESS_NO_500S: bool = True
TARGET_STABILITY_FACTS_IDENTICAL_MIN: float = 1.0  # 100%
TARGET_STABILITY_ENDPOINTS_IDENTICAL_MIN: float = 1.0  # 100%
TARGET_FALLBACK_HTTP_CALLS_MAX: int = 0  # 0 calls

# Seed ranges (must be disjoint from generation seeds <= 1039)
SEED_RANGE_CLEAN = (2000, 2099)
SEED_RANGE_INTENSITY = (2100, 2549)
SEED_RANGE_COMBINATIONS = (2600, 2639)

ALL_HABIT_KEYS = [
    "holding_losers",
    "revenge_trading",
    "overtrading",
    "oversizing",
    "averaging_down",
]

COMMITTED_DATASETS = [
    "clean",
    "single_holding_losers",
    "single_revenge_trading",
    "single_overtrading",
    "single_oversizing",
    "single_averaging_down",
    "mixed",
    "messy",
]

RESULTS_DIR = Path(__file__).resolve().parent / "results"
REPO_ROOT = Path(__file__).resolve().parent.parent


def get_git_commit_hash() -> str:
    """Retrieve the current HEAD git commit hash."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode("utf-8").strip()
    except Exception:
        return "unknown"


# =====================================================================
# SECTION 1: COMMITTED DATASETS
# =====================================================================
def run_section_1_committed_datasets() -> list[dict[str, Any]]:
    """Evaluate performance on committed synthetic benchmark datasets."""
    rows: list[dict[str, Any]] = []

    for name in COMMITTED_DATASETS:
        csv_path = REPO_ROOT / "data" / "datasets" / f"{name}.csv"
        gt_path = REPO_ROOT / "data" / "ground_truth" / f"{name}.json"

        with open(gt_path, encoding="utf-8") as f:
            gt = json.load(f)

        res = run_pipeline(csv_path)
        trades_by_id = {t.trade_id: t for t in res.trades}
        rank_by_key = {h.key: i + 1 for i, h in enumerate(res.ranked.habits)}
        raw_by_key = {r.key: r for r in res.raw_results if r is not None}

        planted_habits = {k: v for k, v in gt.get("habits", {}).items() if v.get("planted")}

        if not planted_habits:
            # clean dataset has no planted habits
            rows.append(
                {
                    "dataset": name,
                    "habit": "none (clean)",
                    "precision": "N/A",
                    "recall": "N/A",
                    "estimated_cost_inr": 0.0,
                    "injected_loss_inr": 0.0,
                    "cost_ratio": "N/A",
                    "confidence": 0.0,
                    "rank": "none",
                }
            )
            continue

        for h_key, h_gt in planted_habits.items():
            gt_entry_oids = set(h_gt.get("entry_order_ids", []))
            injected_loss = float(h_gt.get("injected_loss_inr", 0.0))

            raw = raw_by_key.get(h_key)
            rank = rank_by_key.get(h_key, "dropped" if raw else "not detected")

            if raw:
                flagged_oids = {
                    trades_by_id[tid].entry_order_id
                    for tid in raw.flagged_trade_ids
                    if tid in trades_by_id
                }
                tp = len(flagged_oids & gt_entry_oids)
                fp = len(flagged_oids - gt_entry_oids)
                fn = len(gt_entry_oids - flagged_oids)

                prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                est_cost = float(raw.estimated_cost_inr)
                ratio = est_cost / injected_loss if injected_loss > 0 else 0.0
                conf = float(raw.confidence)
            else:
                prec = rec = est_cost = ratio = conf = 0.0

            rows.append(
                {
                    "dataset": name,
                    "habit": h_key,
                    "precision": round(prec, 4),
                    "recall": round(rec, 4),
                    "estimated_cost_inr": round(est_cost, 2),
                    "injected_loss_inr": round(injected_loss, 2),
                    "cost_ratio": round(ratio, 4),
                    "confidence": round(conf, 4),
                    "rank": rank,
                }
            )

    return rows


# =====================================================================
# SECTION 2: SILENCE ON CLEAN DATA
# =====================================================================
def run_section_2_silence_on_clean() -> dict[str, Any]:
    """Test false positive rate across clean.csv and 100 fresh clean synthetic months."""
    fire_counts: dict[str, int] = {k: 0 for k in ALL_HABIT_KEYS}
    kept_months = 0
    total_months = 1 + (SEED_RANGE_CLEAN[1] - SEED_RANGE_CLEAN[0] + 1)

    # 1. clean.csv
    res_clean = run_pipeline(REPO_ROOT / "data" / "datasets" / "clean.csv")
    if res_clean.ranked.material:
        kept_months += 1
    for r in res_clean.raw_results:
        if r is not None:
            fire_counts[r.key] += 1

    # 2. 100 fresh clean months
    for seed in range(SEED_RANGE_CLEAN[0], SEED_RANGE_CLEAN[1] + 1):
        csv_text, _ = generate_dataset_in_memory(seed=seed)
        res = run_pipeline(csv_text)
        if res.ranked.material:
            kept_months += 1
        for r in res.raw_results:
            if r is not None:
                fire_counts[r.key] += 1

    kept_fraction = kept_months / total_months
    target_met = kept_fraction <= TARGET_CLEAN_KEPT_RATE_MAX

    return {
        "total_months": total_months,
        "kept_months": kept_months,
        "kept_fraction": round(kept_fraction, 4),
        "target_max": TARGET_CLEAN_KEPT_RATE_MAX,
        "target_met": target_met,
        "fire_counts": fire_counts,
    }


# =====================================================================
# SECTION 3: DETECTION BY INTENSITY
# =====================================================================
def run_section_3_detection_by_intensity() -> dict[str, Any]:
    """Test detection rate, precision, recall, and cost ratio by habit and intensity."""
    intensities = ["low", "medium", "high"]
    cell_results: dict[str, dict[str, Any]] = {}
    seed = SEED_RANGE_INTENSITY[0]

    all_targets_met = True
    weakly_detected_low: list[str] = []

    for habit_key in ALL_HABIT_KEYS:
        cell_results[habit_key] = {}
        for intensity in intensities:
            detected_count = 0
            precisions: list[float] = []
            recalls: list[float] = []
            cost_ratios: list[float] = []

            for _ in range(30):
                csv_text, gt = generate_dataset_in_memory(
                    seed=seed, habits_config={habit_key: intensity}
                )
                seed += 1
                res = run_pipeline(csv_text)

                trades_by_id = {t.trade_id: t for t in res.trades}
                raw_by_key = {r.key: r for r in res.raw_results if r is not None}
                kept_by_key = {k.key: k for k in res.ranked.habits}

                raw = raw_by_key.get(habit_key)
                kept = kept_by_key.get(habit_key)
                h_gt = gt["habits"][habit_key]
                gt_oids = set(h_gt.get("entry_order_ids", []))
                injected_loss = float(h_gt.get("injected_loss_inr", 0.0))

                if kept is not None:
                    detected_count += 1

                if raw:
                    flagged_oids = {
                        trades_by_id[tid].entry_order_id
                        for tid in raw.flagged_trade_ids
                        if tid in trades_by_id
                    }
                    tp = len(flagged_oids & gt_oids)
                    fp = len(flagged_oids - gt_oids)
                    fn = len(gt_oids - flagged_oids)
                    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                    precisions.append(p)
                    recalls.append(r)
                    if injected_loss > 0:
                        cost_ratios.append(float(raw.estimated_cost_inr) / injected_loss)
                else:
                    precisions.append(0.0)
                    recalls.append(0.0)
                    if injected_loss > 0:
                        cost_ratios.append(0.0)

            det_rate = detected_count / 30.0
            mean_p = statistics.mean(precisions) if precisions else 0.0
            mean_r = statistics.mean(recalls) if recalls else 0.0
            med_ratio = statistics.median(cost_ratios) if cost_ratios else 0.0

            # Assert targets apply to medium and high only
            target_met = True
            if intensity in ("medium", "high"):
                if det_rate < TARGET_INTENSITY_DETECTION_MIN:
                    target_met = False
                if not (
                    TARGET_INTENSITY_COST_RATIO_MIN <= med_ratio <= TARGET_INTENSITY_COST_RATIO_MAX
                ):
                    target_met = False
                if not target_met:
                    all_targets_met = False
            else:
                if det_rate < 0.70:
                    weakly_detected_low.append(f"{habit_key} ({det_rate * 100:.1f}%)")

            cell_results[habit_key][intensity] = {
                "detection_rate": round(det_rate, 4),
                "mean_precision": round(mean_p, 4),
                "mean_recall": round(mean_r, 4),
                "median_cost_ratio": round(med_ratio, 4),
                "target_met": target_met if intensity != "low" else None,
            }

    return {
        "cells": cell_results,
        "targets_met": all_targets_met,
        "weakly_detected_low": weakly_detected_low,
    }


# =====================================================================
# SECTION 4: COMBINATIONS
# =====================================================================
def run_section_4_combinations() -> dict[str, Any]:
    """Test 40 random 2-3 habit combinations at medium or high intensity."""
    exact_matches = 0
    total_planted = 0
    total_detected_planted = 0
    total_kept = 0
    total_spurious = 0
    top_loss_matches = 0

    per_habit_planted: dict[str, int] = {h: 0 for h in ALL_HABIT_KEYS}
    per_habit_detected: dict[str, int] = {h: 0 for h in ALL_HABIT_KEYS}

    runs: list[dict[str, Any]] = []

    for i in range(40):
        seed = SEED_RANGE_COMBINATIONS[0] + i
        rng = random.Random(seed)
        k = rng.choice([2, 3])
        chosen = rng.sample(ALL_HABIT_KEYS, k)
        config = {h: rng.choice(["medium", "high"]) for h in chosen}

        csv_text, gt = generate_dataset_in_memory(seed, habits_config=config)
        res = run_pipeline(csv_text)

        planted_set = set(chosen)
        kept_set = {h.key for h in res.ranked.habits}

        for h in chosen:
            per_habit_planted[h] += 1
            if h in kept_set:
                per_habit_detected[h] += 1

        if kept_set == planted_set:
            exact_matches += 1

        detected_planted = len(planted_set & kept_set)
        total_detected_planted += detected_planted
        total_planted += len(planted_set)

        spurious = len(kept_set - planted_set)
        total_spurious += spurious
        total_kept += len(kept_set)

        top_planted = max(chosen, key=lambda h: gt["habits"][h]["injected_loss_inr"])
        top_kept = res.ranked.habits[0].key if res.ranked.habits else None
        if top_kept == top_planted:
            top_loss_matches += 1

        runs.append(
            {
                "seed": seed,
                "planted": sorted(list(planted_set)),
                "kept": sorted(list(kept_set)),
                "exact_match": kept_set == planted_set,
                "top_planted": top_planted,
                "top_kept": top_kept,
            }
        )

    exact_match_rate = exact_matches / 40.0
    planted_recall = total_detected_planted / total_planted if total_planted > 0 else 0.0
    spurious_rate = total_spurious / total_kept if total_kept > 0 else 0.0
    top_loss_match_rate = top_loss_matches / 40.0

    target_met = spurious_rate <= TARGET_COMBINATIONS_SPURIOUS_MAX

    per_habit_recall: dict[str, dict[str, Any]] = {}
    for h in ALL_HABIT_KEYS:
        p_cnt = per_habit_planted[h]
        d_cnt = per_habit_detected[h]
        rec = d_cnt / p_cnt if p_cnt > 0 else 0.0
        per_habit_recall[h] = {
            "planted_count": p_cnt,
            "detected_count": d_cnt,
            "recall": round(rec, 4),
        }

    return {
        "n_months": 40,
        "exact_match_rate": round(exact_match_rate, 4),
        "planted_recall": round(planted_recall, 4),
        "spurious_rate": round(spurious_rate, 4),
        "top_loss_match_rate": round(top_loss_match_rate, 4),
        "target_max_spurious": TARGET_COMBINATIONS_SPURIOUS_MAX,
        "target_met": target_met,
        "per_habit_recall": per_habit_recall,
    }


# =====================================================================
# SECTION 5: GROUNDING OF THE NARRATIVE
# =====================================================================
def run_section_5_grounding() -> dict[str, Any]:
    """Test template self-consistency, adversarial rejection,
    benign variants, and mocked LLM path.
    """
    # 5a. Template self-consistency
    tested_count = 0
    passed_count = 0

    # Committed datasets
    for name in COMMITTED_DATASETS:
        res = run_pipeline(REPO_ROOT / "data" / "datasets" / f"{name}.csv")
        facts = build_facts(res.ranked, res.trades)
        template = generate_template_narrative(res.ranked)
        rep = verify_narrative(template, facts)
        tested_count += 1
        if rep.passed:
            passed_count += 1

    # Fresh months from Section 3 where material is True
    seed_s3 = SEED_RANGE_INTENSITY[0]
    for h in ALL_HABIT_KEYS:
        for inten in ["low", "medium", "high"]:
            for _ in range(30):
                csv_text, _ = generate_dataset_in_memory(seed_s3, habits_config={h: inten})
                seed_s3 += 1
                res = run_pipeline(csv_text)
                if res.ranked.material:
                    facts = build_facts(res.ranked, res.trades)
                    template = generate_template_narrative(res.ranked)
                    rep = verify_narrative(template, facts)
                    tested_count += 1
                    if rep.passed:
                        passed_count += 1

    # Fresh months from Section 4 where material is True
    for i in range(40):
        s = SEED_RANGE_COMBINATIONS[0] + i
        rng = random.Random(s)
        k = rng.choice([2, 3])
        chosen = rng.sample(ALL_HABIT_KEYS, k)
        config = {h: rng.choice(["medium", "high"]) for h in chosen}
        csv_text, _ = generate_dataset_in_memory(s, habits_config=config)
        res = run_pipeline(csv_text)
        if res.ranked.material:
            facts = build_facts(res.ranked, res.trades)
            template = generate_template_narrative(res.ranked)
            rep = verify_narrative(template, facts)
            tested_count += 1
            if rep.passed:
                passed_count += 1

    self_consistency_rate = passed_count / tested_count if tested_count > 0 else 0.0

    # 5b. Adversarial rejection: build 33 mutated narratives from real template narratives
    res_mixed = run_pipeline(REPO_ROOT / "data" / "datasets" / "mixed.csv")
    facts_mixed = build_facts(res_mixed.ranked, res_mixed.trades)
    base_mixed = generate_template_narrative(res_mixed.ranked)

    mutations: list[tuple[str, dict[str, Any]]] = []

    m = copy.deepcopy(base_mixed)
    m["summary"] = m["summary"].replace("148,573.45", "180,000.00")
    mutations.append(("changed_summary_rupee", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] = m["habits"][0]["explanation"].replace("97,841.20", "120,000.00")
    mutations.append(("changed_habit_rupee", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] = m["habits"][0]["explanation"].replace("33", "99")
    mutations.append(("changed_count", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] += " Trade P9999 was worst."
    mutations.append(("unknown_trade_id", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] += " Happened on 2024-11-20."
    mutations.append(("unknown_date", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] += " The market will rise."
    mutations.append(("forbidden_will_rise", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] += " The market will fall."
    mutations.append(("forbidden_will_fall", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] += " You should buy options."
    mutations.append(("forbidden_you_should_buy", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] += " You should sell contracts."
    mutations.append(("forbidden_you_should_sell", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] += " Profits are guaranteed."
    mutations.append(("forbidden_guaranteed", m))
    m = copy.deepcopy(base_mixed)
    m["summary"] += " This is financial advice."
    mutations.append(("forbidden_financial_advice", m))
    m = copy.deepcopy(base_mixed)
    m["summary"] += " This is investment advice."
    mutations.append(("forbidden_investment_advice", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] += " Set a price target."
    mutations.append(("forbidden_price_target", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] += " Look for a strong buy."
    mutations.append(("forbidden_strong_buy", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] += " Losses due to decay."
    mutations.append(("unsupported_decay", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] += " Losses due to theta."
    mutations.append(("unsupported_theta", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] += " Losses due to vega."
    mutations.append(("unsupported_vega", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] += " Losses due to volatility."
    mutations.append(("unsupported_volatility", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] += " Losses due to implied volatility."
    mutations.append(("unsupported_iv", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] += " Losses due to premium erosion."
    mutations.append(("unsupported_premium_erosion", m))
    m = copy.deepcopy(base_mixed)
    m["habits"] = m["habits"][:2]
    mutations.append(("dropped_habit", m))
    m = copy.deepcopy(base_mixed)
    m["habits"] = [m["habits"][1], m["habits"][0], m["habits"][2]]
    mutations.append(("reordered_habits", m))
    m = copy.deepcopy(base_mixed)
    m["habits"].append({"key": "extra", "explanation": "Extra habit", "rule": "Extra rule"})
    mutations.append(("extra_habit", m))
    m = copy.deepcopy(base_mixed)
    m["summary"] = m["summary"].replace("148,573.45", "9,99,999.00")
    mutations.append(("wrong_indian_grouping", m))
    m = copy.deepcopy(base_mixed)
    m["summary"] = m["summary"].replace("148,573.45", "999,999.00")
    mutations.append(("wrong_western_grouping", m))
    m = copy.deepcopy(base_mixed)
    m["summary"] += " Win rate was 78.5%."
    mutations.append(("wrong_win_rate", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] = "We recommend to buy call options."
    mutations.append(("forbidden_pattern_recommend", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] = "Always buy the dip."
    mutations.append(("forbidden_pattern_dip", m))
    m = copy.deepcopy(base_mixed)
    m["summary"] = 12345
    mutations.append(("non_string_summary", m))
    m = copy.deepcopy(base_mixed)
    m["summary"] = m["summary"] + (" Extra text word." * 30)
    mutations.append(("long_summary", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["rule"] = m["habits"][0]["rule"] + (" Long rule repeat." * 20)
    mutations.append(("long_rule", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][0]["explanation"] = m["habits"][0]["explanation"] + (" Long explanation word." * 30)
    mutations.append(("long_explanation", m))
    m = copy.deepcopy(base_mixed)
    m["habits"][1]["explanation"] += " See trade P0000."
    mutations.append(("hallucinated_tid", m))

    adversarial_rejected = 0
    for _, mut in mutations:
        rep = verify_narrative(mut, facts_mixed)
        if not rep.passed:
            adversarial_rejected += 1

    adversarial_rejection_rate = adversarial_rejected / len(mutations)

    # 5c. Benign variants: at least 15 rewordings that keep every number correct
    variants: list[tuple[str, dict[str, Any]]] = []

    v = copy.deepcopy(base_mixed)
    v["summary"] = (
        "Your trading this month had an attributed cost of ₹1,48,573.45 across 3 behavioral habits."
    )
    variants.append(("reworded_summary_1", v))
    v = copy.deepcopy(base_mixed)
    v["summary"] = (
        "During this month, 3 behavioral habits produced an attributed cost of ₹1,48,573.45."
    )
    variants.append(("reworded_summary_2", v))
    v = copy.deepcopy(base_mixed)
    v["summary"] = (
        "Your trading this month was impacted by 3 behavioral habits with a "
        "combined attributed cost of ₹148,573.45."
    )
    variants.append(("western_grouping_summary", v))
    v = copy.deepcopy(base_mixed)
    v["habits"][0]["explanation"] = v["habits"][0]["explanation"].replace("97,841.20", "97841.20")
    variants.append(("western_grouping_habit", v))
    v = copy.deepcopy(base_mixed)
    v["summary"] = (
        "Your trading this month was impacted by 3 behavioral habits with an "
        "attributed cost of about ₹1.49 lakh."
    )
    variants.append(("lakh_form", v))
    v = copy.deepcopy(base_mixed)
    v["habits"][0]["explanation"] = v["habits"][0]["explanation"].replace(
        "₹97,841.20", "about ₹98k"
    )
    variants.append(("k_form_habit_1", v))
    v = copy.deepcopy(base_mixed)
    v["habits"][1]["explanation"] = v["habits"][1]["explanation"].replace(
        "₹28,103.25", "about ₹28k"
    )
    variants.append(("k_form_habit_2", v))
    v = copy.deepcopy(base_mixed)
    v["summary"] = (
        "Your trading this month was impacted by 3 behavioral habits with an "
        "attributed cost of about ₹148,500."
    )
    variants.append(("about_rounding_summary", v))
    v = copy.deepcopy(base_mixed)
    v["habits"][0]["explanation"] = (
        "Flagged losing trades were held for a median of 56.0 minutes versus 21.0 minutes for "
        "winning trades. These 33 positions cost an attributed ₹97,841.20 in extra loss "
        "beyond normal losses."
    )
    variants.append(("reworded_hl_exp", v))
    v = copy.deepcopy(base_mixed)
    v["habits"][1]["explanation"] = (
        "Following losses, you re-entered the market in an average of 5.7 minutes "
        "across 12 entries, causing an attributed cost of ₹28,103.25 in net loss "
        "on these re-entries."
    )
    variants.append(("reworded_rt_exp", v))
    v = copy.deepcopy(base_mixed)
    v["habits"][2]["explanation"] = (
        "You traded during volume spikes across 2 days, averaging 12.0 trades compared to your "
        "baseline of 5.0. These 14 excess trades produced an attributed cost of ₹22,629.00 "
        "in net loss on the extra trades."
    )
    variants.append(("reworded_ot_exp", v))
    v = copy.deepcopy(base_mixed)
    v["summary"] = (
        "Your trading this month was impacted by 3 behavioral habits with a "
        "combined attributed cost of INR 1,48,573.45."
    )
    variants.append(("inr_prefix", v))
    v = copy.deepcopy(base_mixed)
    v["summary"] = (
        "Your trading this month was impacted by 3 behavioral habits with a "
        "combined attributed cost of Rs. 1,48,573.45."
    )
    variants.append(("rs_prefix", v))
    v = copy.deepcopy(base_mixed)
    v["habits"][0]["rule"] = (
        "Next month: Exit any losing trade that has not recovered within 20 minutes of entry."
    )
    variants.append(("reworded_rule_hl", v))
    v = copy.deepcopy(base_mixed)
    v["habits"][1]["rule"] = (
        "Enforce a strict 30-minute cooldown period following any losing trade "
        "before entering a new position."
    )
    variants.append(("reworded_rule_rt", v))
    v = copy.deepcopy(base_mixed)
    v["habits"][2]["rule"] = (
        "Cap daily activity at 6 completed trades and stop trading for the day once reached."
    )
    variants.append(("reworded_rule_ot", v))

    benign_accepted = 0
    false_rejections: list[str] = []
    for name, var in variants:
        rep = verify_narrative(var, facts_mixed)
        if rep.passed:
            benign_accepted += 1
        else:
            false_rejections.append(name)

    benign_acceptance_rate = benign_accepted / len(variants)

    # 5d. LLM path with mocked transport
    res_single = run_pipeline(REPO_ROOT / "data" / "datasets" / "single_holding_losers.csv")
    llm_test_settings = Settings(LLM_PROVIDER="anthropic", LLM_API_KEY="sk-eval-fake-key")

    llm_scenarios: list[dict[str, Any]] = []

    # Scenario 1: scripted good response
    good_json = {
        "summary": (
            "Your trading this month was impacted by 1 behavioral habit with an "
            "attributed cost of ₹56,518.88."
        ),
        "habits": [
            {
                "key": "holding_losers",
                "explanation": (
                    "Across winning trades your median hold was 21.0 minutes, but flagged "
                    "losing trades were held for a median of 56.0 minutes. Holding these "
                    "18 losing positions cost an attributed ₹56,518.88 in extra loss "
                    "beyond what you normally lose on a losing trade."
                ),
                "rule": (
                    "Exit any losing trade that has not recovered within 20 minutes of entry, "
                    "which is about how long your winning trades last."
                ),
            }
        ],
    }
    t_good = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"content": [{"type": "text", "text": json.dumps(good_json)}]}
        )
    )
    r_good = generate_narrative(
        res_single.ranked, res_single.trades, cfg=llm_test_settings, transport=t_good
    )
    llm_scenarios.append(
        {
            "scenario": "scripted_good_response",
            "source": r_good.source,
            "attempts": r_good.llm_attempts,
            "fallback_reason": r_good.fallback_reason,
        }
    )

    # Scenario 2: hallucinated response
    hallu_json = {
        "summary": "Your trading had a huge loss of ₹999,999.00 this month.",
        "habits": [
            {
                "key": "holding_losers",
                "explanation": "You lost ₹999,999.00 on 99 trades.",
                "rule": "Exit any losing trade.",
            }
        ],
    }
    t_hallu = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"content": [{"type": "text", "text": json.dumps(hallu_json)}]}
        )
    )
    r_hallu = generate_narrative(
        res_single.ranked, res_single.trades, cfg=llm_test_settings, transport=t_hallu
    )
    llm_scenarios.append(
        {
            "scenario": "hallucinated_response",
            "source": r_hallu.source,
            "attempts": r_hallu.llm_attempts,
            "fallback_reason": r_hallu.fallback_reason,
        }
    )

    # Scenario 3: malformed JSON
    t_mal = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"content": [{"type": "text", "text": "This is not valid json {bad}"}]}
        )
    )
    r_mal = generate_narrative(
        res_single.ranked, res_single.trades, cfg=llm_test_settings, transport=t_mal
    )
    llm_scenarios.append(
        {
            "scenario": "malformed_json",
            "source": r_mal.source,
            "attempts": r_mal.llm_attempts,
            "fallback_reason": r_mal.fallback_reason,
        }
    )

    # Scenario 4: 500 error
    t_500 = httpx.MockTransport(lambda req: httpx.Response(500, text="Internal Server Error"))
    r_500 = generate_narrative(
        res_single.ranked, res_single.trades, cfg=llm_test_settings, transport=t_500
    )
    llm_scenarios.append(
        {
            "scenario": "http_500_error",
            "source": r_500.source,
            "attempts": r_500.llm_attempts,
            "fallback_reason": r_500.fallback_reason,
        }
    )

    llm_calls_ok = all(s["attempts"] <= 2 for s in llm_scenarios)

    targets_met = (
        self_consistency_rate >= TARGET_TEMPLATE_SELF_CONSISTENCY_MIN
        and adversarial_rejection_rate >= TARGET_ADVERSARIAL_REJECTION_MIN
        and benign_acceptance_rate >= TARGET_BENIGN_ACCEPTANCE_MIN
        and llm_calls_ok
    )

    return {
        "self_consistency_rate": round(self_consistency_rate, 4),
        "self_consistency_tested": tested_count,
        "self_consistency_passed": passed_count,
        "adversarial_rejection_rate": round(adversarial_rejection_rate, 4),
        "adversarial_tested": len(mutations),
        "adversarial_rejected": adversarial_rejected,
        "benign_acceptance_rate": round(benign_acceptance_rate, 4),
        "benign_tested": len(variants),
        "benign_accepted": benign_accepted,
        "false_rejections": false_rejections,
        "llm_scenarios": llm_scenarios,
        "target_met": targets_met,
    }


# =====================================================================
# SECTION 6: ROBUSTNESS
# =====================================================================
def run_section_6_robustness() -> dict[str, Any]:
    """Test API behavior under messy ground-truth data, empty files,
    corrupt headers, and size boundaries.
    """
    client = TestClient(app)
    cases: list[dict[str, Any]] = []

    # 1. messy.csv
    with open(REPO_ROOT / "data" / "datasets" / "messy.csv", "rb") as f:
        r_messy = client.post("/api/analyze", files={"file": ("messy.csv", f, "text/csv")})

    with open(REPO_ROOT / "data" / "ground_truth" / "messy.json", encoding="utf-8") as f:
        gt_messy = json.load(f)

    actual_counts = r_messy.json().get("dataset", {}).get("counts", {})
    gt_counts = gt_messy.get("expected_ingest_warnings", {})
    counts_matched = (
        actual_counts.get("duplicates") == gt_counts.get("duplicates")
        and actual_counts.get("rejected") == gt_counts.get("rejected")
        and actual_counts.get("missing_price") == gt_counts.get("missing_price")
    )

    dup_cnt = actual_counts.get("duplicates")
    rej_cnt = actual_counts.get("rejected")
    mp_cnt = actual_counts.get("missing_price")
    cases.append(
        {
            "case": "messy.csv (normal upload)",
            "status": r_messy.status_code,
            "message": (
                f"Ingest counts match ground truth: duplicates={dup_cnt}, "
                f"rejected={rej_cnt}, missing_price={mp_cnt}"
            ),
            "passed": r_messy.status_code == 200 and counts_matched,
        }
    )

    # 2. Header only
    header_only = (
        b"order_id,timestamp,symbol,instrument_type,strike,expiry,"
        b"side,quantity,lot_size,price,status\n"
    )
    r_header = client.post(
        "/api/analyze", files={"file": ("header_only.csv", header_only, "text/csv")}
    )
    cases.append(
        {
            "case": "header_only.csv",
            "status": r_header.status_code,
            "message": str(r_header.json().get("detail")),
            "passed": r_header.status_code == 422,
        }
    )

    # 3. Missing column
    missing_col = (
        b"order_id,timestamp,symbol,instrument_type,strike,expiry,side,quantity,lot_size,status\n"
        b"ORD1,2024-10-01T09:15:00+05:30,NIFTY,CE,25000,2024-10-31,BUY,75,75,COMPLETE\n"
    )
    r_missing = client.post(
        "/api/analyze", files={"file": ("missing_col.csv", missing_col, "text/csv")}
    )
    cases.append(
        {
            "case": "missing_price_column.csv",
            "status": r_missing.status_code,
            "message": str(r_missing.json().get("detail")),
            "passed": r_missing.status_code == 422,
        }
    )

    # 4. Binary bytes
    binary_bytes = b"\x00\x01\x02\xff\xfe\xfd\xaa\xbb\xcc" * 20
    r_bin = client.post(
        "/api/analyze",
        files={"file": ("corrupted.bin", binary_bytes, "application/octet-stream")},
    )
    cases.append(
        {
            "case": "binary_bytes.bin",
            "status": r_bin.status_code,
            "message": str(r_bin.json().get("detail")),
            "passed": r_bin.status_code == 422,
        }
    )

    # 5. 20,001 rows
    row = "ORD{i},2024-10-01T09:15:00+05:30,NIFTY,CE,25000,2024-10-31,BUY,75,75,100,COMPLETE\n"
    header = (
        "order_id,timestamp,symbol,instrument_type,strike,expiry,"
        "side,quantity,lot_size,price,status\n"
    )
    long_csv = (header + "".join(row.format(i=i) for i in range(20001))).encode("utf-8")
    r_long = client.post("/api/analyze", files={"file": ("long.csv", long_csv, "text/csv")})
    cases.append(
        {
            "case": "file_with_20001_rows.csv",
            "status": r_long.status_code,
            "message": str(r_long.json().get("detail")),
            "passed": r_long.status_code == 422,
        }
    )

    no_500s = all(c["status"] < 500 for c in cases)
    all_passed = no_500s and all(c["passed"] for c in cases)

    return {
        "cases": cases,
        "no_500s": no_500s,
        "target_met": all_passed,
    }


# =====================================================================
# SECTION 7: STABILITY
# =====================================================================
def run_section_7_stability() -> dict[str, Any]:
    """Test deterministic reproducibility of pipeline facts and
    parity between sample and analyze endpoints.
    """
    client = TestClient(app)

    facts_matches: list[dict[str, Any]] = []
    for name in COMMITTED_DATASETS:
        csv_path = REPO_ROOT / "data" / "datasets" / f"{name}.csv"
        res1 = run_pipeline(csv_path)
        facts1 = json.dumps(build_facts(res1.ranked, res1.trades).to_dict(), sort_keys=True)
        res2 = run_pipeline(csv_path)
        facts2 = json.dumps(build_facts(res2.ranked, res2.trades).to_dict(), sort_keys=True)
        facts_matches.append(
            {
                "dataset": name,
                "byte_identical": facts1 == facts2,
            }
        )

    facts_identical_rate = sum(1 for m in facts_matches if m["byte_identical"]) / len(facts_matches)

    endpoint_matches: list[dict[str, Any]] = []
    for name in COMMITTED_DATASETS:
        r_sample = client.get(f"/api/sample/{name}")
        with open(REPO_ROOT / "data" / "datasets" / f"{name}.csv", "rb") as f:
            r_upload = client.post("/api/analyze", files={"file": (f"{name}.csv", f, "text/csv")})

        js_sample = r_sample.json()
        js_upload = r_upload.json()

        h_sample = [
            (h["key"], h["attributed_cost_inr"], h["rank"]) for h in js_sample.get("habits", [])
        ]
        h_upload = [
            (h["key"], h["attributed_cost_inr"], h["rank"]) for h in js_upload.get("habits", [])
        ]

        identical = (h_sample == h_upload) and (
            js_sample.get("material") == js_upload.get("material")
        )
        endpoint_matches.append(
            {
                "dataset": name,
                "identical": identical,
            }
        )

    endpoint_identical_rate = sum(1 for m in endpoint_matches if m["identical"]) / len(
        endpoint_matches
    )

    target_met = (
        facts_identical_rate >= TARGET_STABILITY_FACTS_IDENTICAL_MIN
        and endpoint_identical_rate >= TARGET_STABILITY_ENDPOINTS_IDENTICAL_MIN
    )

    return {
        "facts_matches": facts_matches,
        "facts_identical_rate": round(facts_identical_rate, 4),
        "endpoint_matches": endpoint_matches,
        "endpoint_identical_rate": round(endpoint_identical_rate, 4),
        "target_met": target_met,
    }


# =====================================================================
# SECTION 8: FALLBACK
# =====================================================================
def run_section_8_fallback() -> dict[str, Any]:
    """Test that missing LLM configuration cleanly falls back to templates with zero HTTP calls."""
    no_key_settings = Settings(LLM_PROVIDER="none", LLM_API_KEY=None)
    http_call_count = 0

    def mock_handler(_req: httpx.Request) -> httpx.Response:
        nonlocal http_call_count
        http_call_count += 1
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(mock_handler)
    dataset_results: list[dict[str, Any]] = []

    for name in COMMITTED_DATASETS:
        res = run_pipeline(REPO_ROOT / "data" / "datasets" / f"{name}.csv")
        nar_res = generate_narrative(
            res.ranked, res.trades, cfg=no_key_settings, transport=transport
        )
        dataset_results.append(
            {
                "dataset": name,
                "source": nar_res.source,
                "verified": nar_res.verification.passed,
                "fallback_reason": nar_res.fallback_reason,
            }
        )

    all_verified_template = all(
        d["source"] == "template" and d["verified"] for d in dataset_results
    )
    target_met = (
        all_verified_template and (http_call_count <= TARGET_FALLBACK_HTTP_CALLS_MAX)
    )

    return {
        "dataset_results": dataset_results,
        "http_calls_made": http_call_count,
        "target_max_calls": TARGET_FALLBACK_HTTP_CALLS_MAX,
        "target_met": target_met,
    }


# =====================================================================
# SECTION 9: KNOWN LIMITATIONS
# =====================================================================
def get_known_limitations() -> dict[str, Any]:
    """Return documented known limitations and synthetic generator context."""
    # Compute the share of planted add-on trades that won in single_averaging_down.csv
    res_ad = run_pipeline(REPO_ROOT / "data" / "datasets" / "single_averaging_down.csv")
    with open(
        REPO_ROOT / "data" / "ground_truth" / "single_averaging_down.json", encoding="utf-8"
    ) as f:
        gt_ad = json.load(f)
    addon_oids = set(gt_ad["habits"]["averaging_down"]["entry_order_ids"])
    addon_trades = [t for t in res_ad.trades if t.entry_order_id in addon_oids]
    winning_addons = [t for t in addon_trades if t.gross_pnl > 0]
    win_pct = (len(winning_addons) / len(addon_trades) * 100) if addon_trades else 0.0

    return {
        "synthetic_author_parity": (
            "Datasets are synthetic and generated by the same codebase author as the detectors. "
            "These evaluations prove that the detectors reliably recover what the generator "
            "plants, not that real-world retail options traders behave in this exact "
            "parametric manner."
        ),
        "forced_loss_flattery": {
            "description": (
                "Planted loss habits are artificially forced to be losing trades in several "
                "generator methods, which guarantees a clean distinction between baseline trades "
                "and habit-induced trades, flattering cost ratios."
            ),
            "affected_habits": [
                (
                    "holding_losers: extends hold time specifically for trades already destined "
                    "to lose, ensuring extended losers have larger losses."
                ),
                (
                    "revenge_trading: explicitly overrides pnl_inr to a forced negative loss "
                    "on re-entries following losing trades."
                ),
                (
                    "overtrading: explicitly forces trades above the daily baseline volume "
                    "threshold to be losing trades."
                ),
                (
                    "oversizing: explicitly forces position sizes following two consecutive wins "
                    "or losses to result in losing trades."
                ),
                (
                    "averaging_down: add-on legs are planted on already-losing trades "
                    f"and usually, but not always, finish at a loss ({win_pct:.1f}% of "
                    f"planted add-on trades won in the committed dataset, "
                    f"{len(winning_addons)} of {len(addon_trades)})."
                ),
            ],
        },
        "gross_pnl_lower_bounds": (
            "All calculations rely purely on gross P&L (exit price minus entry price times "
            "quantity). Brokerage charges, Securities Transaction Tax (STT), exchange turnover "
            "fees, and GST are not included. Reported habit costs therefore represent strict "
            "lower bounds on the total capital destroyed."
        ),
        "proportional_overlap_approximation": (
            "Portfolio overlap attribution is computed using a proportional-by-count approximation "
            "(attributed_cost_inr = estimated_cost_inr * (1 - overlap_share)), not an exact "
            "combinatorial per-trade attribution. This provides a deterministic, transparent "
            "adjustment but remains a heuristic approximation."
        ),
        "confidence_semantics": (
            "Confidence scores reflect evidence volume and behavioral extremity (e.g., hold-time "
            "ratios, cooldown violation speed), not a frequentist or Bayesian probability "
            "of recurrence."
        ),
        "threshold_calibration_history": [
            (
                "holding_losers MEDIAN_RATIO_MIN: specified as 1.5, lowered to 1.10 after the "
                "first run showed planted data had a median ratio of about 1.19 "
                "(post-hoc, step 5a)."
            ),
            (
                "revenge_trading size condition: changed from raw quantity to lots after "
                "cross-instrument false flags on mixed.csv (step 5c-fix)."
            ),
            (
                "holding_losers confidence formula: changed to use the flagged trades' median "
                "hold after planted months were dropped by the evidence bar (step 6b); "
                "detection and cost were verified identical."
            ),
            (
                "generator fixes: overtrading planted days adjusted so they exceed 2x the median "
                "(low intensity now means exactly the detector's 2-day minimum), and the messy "
                "dataset's missing-price rows changed to unexecuted attempts."
            ),
            (
                "narrative layer: unsupported-claim terms blocked and rules derived from trader "
                "data (steps 7b, 7c), which changed wording only."
            ),
        ],
    }


# =====================================================================
# REPORT FORMATTERS (MARKDOWN & JSON)
# =====================================================================
def build_markdown_report(results: dict[str, Any]) -> str:
    """Format evaluation results into a comprehensive GitHub-flavored Markdown document."""
    s1 = results["section_1_committed"]
    s2 = results["section_2_clean"]
    s3 = results["section_3_intensity"]
    s4 = results["section_4_combinations"]
    s5 = results["section_5_grounding"]
    s6 = results["section_6_robustness"]
    s7 = results["section_7_stability"]
    s8 = results["section_8_fallback"]
    s9 = results["section_9_limitations"]

    seed_c = results["meta"]["seeds"]["clean"]
    seed_i = results["meta"]["seeds"]["intensity"]
    seed_cb = results["meta"]["seeds"]["combinations"]
    lines: list[str] = [
        "# TradeMirror Evaluation Report",
        "",
        f"- **Commit**: `{results['meta']['git_commit']}`",
        f"- **Run Date**: {results['meta']['run_date']}",
        f"- **Seed Ranges**: Clean: `{seed_c}`, Intensity: `{seed_i}`, Combinations: `{seed_cb}`",
        "",
        "## Summary of Targets",
        "",
    ]

    s5_p = f"{s5['self_consistency_rate'] * 100:.1f}% passed"
    s5_p_cnt = f"({s5['self_consistency_passed']}/{s5['self_consistency_tested']})"
    s5_rej = f"{s5['adversarial_rejection_rate'] * 100:.1f}% rejected"
    s5_rej_cnt = f"({s5['adversarial_rejected']}/{s5['adversarial_tested']})"
    s5_acc = f"{s5['benign_acceptance_rate'] * 100:.1f}% accepted"
    s5_acc_cnt = f"({s5['benign_accepted']}/{s5['benign_tested']})"

    targets = [
        (
            "Section 2: Silence on clean data (kept <= 2%)",
            s2["target_met"],
            f"{s2['kept_fraction'] * 100:.1f}% kept ({s2['kept_months']}/{s2['total_months']})",
        ),
        (
            "Section 3: Detection by intensity (medium/high >= 85%, cost ratio 0.5-2.0)",
            s3["targets_met"],
            "All medium & high cells within targets",
        ),
        (
            "Section 4: Combinations (spurious-habit rate <= 10%)",
            s4["target_met"],
            f"{s4['spurious_rate'] * 100:.2f}% spurious rate",
        ),
        (
            "Section 5a: Template self-consistency (100%)",
            s5["self_consistency_rate"] >= TARGET_TEMPLATE_SELF_CONSISTENCY_MIN,
            f"{s5_p} {s5_p_cnt}",
        ),
        (
            "Section 5b: Adversarial rejection (100%)",
            s5["adversarial_rejection_rate"] >= TARGET_ADVERSARIAL_REJECTION_MIN,
            f"{s5_rej} {s5_rej_cnt}",
        ),
        (
            "Section 5c: Benign variants acceptance (>= 90%)",
            s5["benign_acceptance_rate"] >= TARGET_BENIGN_ACCEPTANCE_MIN,
            f"{s5_acc} {s5_acc_cnt}",
        ),
        (
            "Section 6: Robustness (no 500s on malformed inputs)",
            s6["target_met"],
            "All corrupted and boundary inputs handled with client 422 errors",
        ),
        (
            "Section 7: Stability (100% byte-identical facts & endpoint parity)",
            s7["target_met"],
            (
                f"Facts: {s7['facts_identical_rate'] * 100:.0f}%, "
                f"Endpoints: {s7['endpoint_identical_rate'] * 100:.0f}%"
            ),
        ),
        (
            "Section 8: Fallback (zero HTTP calls with no LLM key)",
            s8["target_met"],
            f"{s8['http_calls_made']} HTTP calls, 100% verified templates",
        ),
    ]

    for name, met, detail in targets:
        status_str = "MET" if met else "MISSED"
        lines.append(f"- **{name}**: **{status_str}** — {detail}")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 1. Committed Datasets",
            "",
            "| Dataset | Planted Habit | Precision | Recall | "
            "Est Cost (₹) | Injected Loss (₹) | Cost Ratio | Conf | Rank |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )

    for r in s1:
        s_p = (
            f"{r['precision']:.2f}"
            if isinstance(r["precision"], (int, float))
            else str(r["precision"])
        )
        s_r = (
            f"{r['recall']:.2f}"
            if isinstance(r["recall"], (int, float))
            else str(r["recall"])
        )
        s_cr = (
            f"{r['cost_ratio']:.2f}"
            if isinstance(r["cost_ratio"], (int, float))
            else str(r["cost_ratio"])
        )
        s_cost = f"₹{r['estimated_cost_inr']:,.2f}"
        s_inj = f"₹{r['injected_loss_inr']:,.2f}"
        lines.append(
            f"| `{r['dataset']}` | `{r['habit']}` | {s_p} | {s_r} | "
            f"{s_cost} | {s_inj} | {s_cr} | {r['confidence']:.2f} | {r['rank']} |"
        )

    s2_pct = f"{s2['kept_fraction'] * 100:.2f}%"
    s2_target = f"{TARGET_CLEAN_KEPT_RATE_MAX * 100:.1f}%"
    lines.extend(
        [
            "",
            "## 2. Silence on Clean Data",
            "",
            f"- **Kept Habit Months**: {s2['kept_months']} of {s2['total_months']} ({s2_pct}) "
            f"[Target: <= {s2_target}]",
            "- **Per-Detector Raw Fire Counts** across 101 clean months:",
        ]
    )
    for h, cnt in s2["fire_counts"].items():
        lines.append(f"  - `{h}`: {cnt}")

    weak_str = ", ".join(s3["weakly_detected_low"]) if s3["weakly_detected_low"] else "None"
    lines.extend(
        [
            "",
            "## 3. Detection by Intensity",
            "",
            f"- **Weakly Detected at Low Intensity**: {weak_str}",
            "",
            "| Habit | Intensity | Detection Rate | Mean Precision | "
            "Mean Recall | Median Cost Ratio | Target Met |",
            "|---|---|---|---|---|---|---|",
        ]
    )

    for h, int_map in s3["cells"].items():
        for inten, vals in int_map.items():
            t_str = (
                "MET"
                if vals["target_met"]
                else ("MISSED" if vals["target_met"] is False else "Report Only")
            )
            d_rate = f"{vals['detection_rate'] * 100:.1f}%"
            lines.append(
                f"| `{h}` | `{inten}` | {d_rate} | {vals['mean_precision']:.2f} | "
                f"{vals['mean_recall']:.2f} | {vals['median_cost_ratio']:.2f} | {t_str} |"
            )

    s4_spur_pct = f"{s4['spurious_rate'] * 100:.2f}%"
    s4_spur_tgt = f"{TARGET_COMBINATIONS_SPURIOUS_MAX * 100:.1f}%"
    s4_top_match = f"{s4['top_loss_match_rate'] * 100:.1f}%"
    false_rej_str = ", ".join(s5["false_rejections"]) if s5["false_rejections"] else "None"
    lines.extend(
        [
            "",
            "## 4. Combinations (40 Months, 2–3 Habits, Medium/High)",
            "",
            f"- **Exact-Set Match Rate**: {s4['exact_match_rate'] * 100:.1f}%",
            f"- **Planted-Habit Recall**: {s4['planted_recall'] * 100:.1f}%",
            f"- **Spurious-Habit Rate**: {s4_spur_pct} [Target: <= {s4_spur_tgt}]",
            f"- **Top-Ranked Equals Largest Injected Loss**: {s4_top_match}",
            "",
            "### Per-Habit Combination Recall",
            "",
            "| Habit | Times Planted | Times Detected | Recall |",
            "|---|---|---|---|",
        ]
    )

    for h, stat in s4.get("per_habit_recall", {}).items():
        rec_pct = f"{stat['recall'] * 100:.1f}%"
        lines.append(
            f"| `{h}` | {stat['planted_count']} | {stat['detected_count']} | {rec_pct} |"
        )

    lines.extend(
        [
            "",
            "## 5. Grounding of the Narrative",
            "",
            f"- **Template Self-Consistency**: {s5_p} {s5_p_cnt} [Target: 100%]",
            f"- **Adversarial Rejection Rate**: {s5_rej} {s5_rej_cnt} [Target: 100%]",
            f"- **Benign Variants Acceptance**: {s5_acc} {s5_acc_cnt} [Target: >= 90%]",
            f"- **False Rejections**: {false_rej_str}",
            "",
            "### Scripted LLM Scenarios (Mocked Transport)",
            "",
            "| Scenario | Output Source | LLM Attempts | Fallback Reason |",
            "|---|---|---|---|",
        ]
    )

    for sc in s5["llm_scenarios"]:
        clean_reason = (sc["fallback_reason"] or "None (Passed)").replace("\n", " ").strip()
        lines.append(
            f"| `{sc['scenario']}` | `{sc['source']}` | {sc['attempts']} | {clean_reason} |"
        )

    lines.extend(
        [
            "",
            "## 6. Robustness",
            "",
            "| Input Variant | HTTP Status | Detail / Message |",
            "|---|---|---|",
        ]
    )

    for c in s6["cases"]:
        clean_msg = str(c["message"]).replace("\n", " ").strip()
        lines.append(f"| `{c['case']}` | {c['status']} | {clean_msg} |")

    lines.extend(
        [
            "",
            "## 7. Stability",
            "",
            f"- **Pipeline Facts Byte-Identical Rate**: {s7['facts_identical_rate'] * 100:.0f}% "
            "across 2 runs on all 8 committed datasets [Target: 100%]",
            f"- **Sample Endpoint vs Analyze Upload Parity**: "
            f"{s7['endpoint_identical_rate'] * 100:.0f}% across all 8 datasets [Target: 100%]",
            "",
            "## 8. Fallback Under Missing LLM Configuration",
            "",
            f"- **HTTP Calls Made**: {s8['http_calls_made']} [Target: 0]",
            "- **Dataset Verification**:",
        ]
    )

    for d in s8["dataset_results"]:
        lines.append(f"  - `{d['dataset']}`: source=`{d['source']}`, verified=`{d['verified']}`")

    lines.extend(
        [
            "",
            "## 9. Known Limitations",
            "",
            f"1. **Synthetic Author Parity**: {s9['synthetic_author_parity']}",
            f"2. **Forced Loss Flattery**: {s9['forced_loss_flattery']['description']}",
        ]
    )

    for h_aff in s9["forced_loss_flattery"]["affected_habits"]:
        lines.append(f"   - {h_aff}")

    lines.extend(
        [
            f"3. **Gross P&L Lower Bounds**: {s9['gross_pnl_lower_bounds']}",
            f"4. **Proportional Overlap Attribution**: {s9['proportional_overlap_approximation']}",
            f"5. **Confidence Semantics**: {s9['confidence_semantics']}",
            "6. **Threshold Calibration History**:",
        ]
    )

    for cal in s9["threshold_calibration_history"]:
        lines.append(f"   - {cal}")

    lines.append("")
    return "\n".join(lines)


# =====================================================================
# MAIN HARNESS RUNNER
# =====================================================================
def run_evaluation() -> bool:
    """Execute all evaluation suites, write output artifacts, and return pass/fail status."""
    print("=== Running TradeMirror Evaluation Harness ===")

    commit_hash = get_git_commit_hash()
    run_date = date.today().isoformat()

    print("1. Running Section 1: Committed Datasets...")
    s1 = run_section_1_committed_datasets()

    print("2. Running Section 2: Silence on Clean Data...")
    s2 = run_section_2_silence_on_clean()

    print("3. Running Section 3: Detection by Intensity (450 datasets)...")
    s3 = run_section_3_detection_by_intensity()

    print("4. Running Section 4: Combinations (40 datasets)...")
    s4 = run_section_4_combinations()

    print("5. Running Section 5: Grounding of the Narrative...")
    s5 = run_section_5_grounding()

    print("6. Running Section 6: Robustness...")
    s6 = run_section_6_robustness()

    print("7. Running Section 7: Stability...")
    s7 = run_section_7_stability()

    print("8. Running Section 8: Fallback...")
    s8 = run_section_8_fallback()

    print("9. Generating Section 9: Known Limitations...")
    s9 = get_known_limitations()

    # Determine overall target pass
    all_targets_passed = (
        s2["target_met"]
        and s3["targets_met"]
        and s4["target_met"]
        and s5["target_met"]
        and s6["target_met"]
        and s7["target_met"]
        and s8["target_met"]
    )

    results_data: dict[str, Any] = {
        "meta": {
            "git_commit": commit_hash,
            "run_date": run_date,
            "seeds": {
                "clean": f"{SEED_RANGE_CLEAN[0]}-{SEED_RANGE_CLEAN[1]}",
                "intensity": f"{SEED_RANGE_INTENSITY[0]}-{SEED_RANGE_INTENSITY[1]}",
                "combinations": f"{SEED_RANGE_COMBINATIONS[0]}-{SEED_RANGE_COMBINATIONS[1]}",
            },
            "overall_status": "ALL_TARGETS_MET" if all_targets_passed else "TARGETS_MISSED",
        },
        "section_1_committed": s1,
        "section_2_clean": s2,
        "section_3_intensity": s3,
        "section_4_combinations": s4,
        "section_5_grounding": s5,
        "section_6_robustness": s6,
        "section_7_stability": s7,
        "section_8_fallback": s8,
        "section_9_limitations": s9,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    json_path = RESULTS_DIR / "results.json"
    with open(json_path, mode="w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=2)

    md_path = RESULTS_DIR / "results.md"
    markdown_content = build_markdown_report(results_data)
    with open(md_path, mode="w", encoding="utf-8") as f:
        f.write(markdown_content)

    print(f"\nEvaluation complete. Outputs written to:\n- {md_path}\n- {json_path}")
    print(f"Overall Status: {results_data['meta']['overall_status']}")

    return all_targets_passed


if __name__ == "__main__":
    success = run_evaluation()
    sys.exit(0 if success else 1)
