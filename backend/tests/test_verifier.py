"""Tests for narrative grounding verifier."""

from __future__ import annotations

from typing import Any

from app.verifier import verify_narrative


def _make_dummy_facts() -> dict[str, Any]:
    """Helper returning a standard facts fixture for verifier unit tests."""
    return {
        "context": {
            "n_trades": 121,
            "gross_pnl_inr": -127453.15,
            "gross_loss_inr": 250416.95,
            "win_rate": 0.405,
            "total_attributed_cost_inr": 148573.45,
        },
        "habits": [
            {
                "key": "holding_losers",
                "name": "Holding losing trades",
                "attributed_cost_inr": 97841.20,
                "overlap_share": 0.0,
                "approved_rule": "Set a hard time stop to exit any losing trade within 30 minutes.",
            },
            {
                "key": "revenge_trading",
                "name": "Revenge trading",
                "attributed_cost_inr": 28103.25,
                "overlap_share": 0.4167,
                "approved_rule": "Enforce a mandatory 30-minute cooldown period.",
            },
        ],
        "allowed_numbers": [
            121.0,
            127453.15,
            250416.95,
            0.405,
            148573.45,
            97841.20,
            28103.25,
            0.4167,
            30.0,
            21.0,
            56.0,
            33.0,
            12.0,
            5.7,
            2.0,
        ],
        "allowed_trade_ids": ["P0010", "P0014", "P0064"],
        "allowed_dates": ["2024-10-01", "2024-10-02"],
    }


def _make_valid_narrative() -> dict[str, Any]:
    """Helper returning a valid narrative strictly matching the dummy facts."""
    return {
        "summary": "Your trading this month was impacted by 2 habits with a cost of ₹1,48,573.45.",
        "habits": [
            {
                "key": "holding_losers",
                "explanation": (
                    "Winning trades had a median hold of 21.0 minutes, but losing "
                    "trades were held for 56.0 minutes. This cost ₹97,841.20 across "
                    "33 trades including trade P0010 on 2024-10-01."
                ),
                "rule": "Set a hard time stop to exit any losing trade within 30 minutes.",
            },
            {
                "key": "revenge_trading",
                "explanation": (
                    "You re-entered within 5.7 minutes after losses across 12 trades "
                    "with 41.7% overlap. This cost an attributed ₹28,103.25."
                ),
                "rule": "Wait for a 30-minute cooldown before any new entry.",
            },
        ],
    }


def test_verifier_passes_correct_narrative() -> None:
    """Verifies that a well-grounded narrative passes all verification checks."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()
    report = verify_narrative(narrative, facts)

    assert report.passed is True
    assert len(report.failures) == 0
    assert "P0010" in report.checked_trade_ids
    assert 97841.20 in report.checked_numbers or any(
        abs(n - 97841.20) < 1.0 for n in report.checked_numbers
    )


def test_verifier_rejects_ungrounded_number() -> None:
    """Verifies that an invented number not in facts fails verification."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()
    # Change cost to ungrounded amount
    narrative["habits"][0]["explanation"] = (
        "Winning trades had a median hold of 21.0 minutes, costing ₹99,999.00."
    )

    report = verify_narrative(narrative, facts)
    assert report.passed is False
    kinds = [f["kind"] for f in report.failures]
    assert "ungrounded_number" in kinds


def test_verifier_rejects_hallucinated_rupee_loss_total() -> None:
    """Explicitly verify rejection of hallucinated ₹2,00,000 claim."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()
    narrative["summary"] = "Your behavioral habits cost you a total of ₹2,00,000 this month."

    report = verify_narrative(narrative, facts)
    assert report.passed is False
    assert any(f["kind"] == "ungrounded_number" and f["value"] == 200000.0 for f in report.failures)


def test_verifier_rejects_unknown_trade_id() -> None:
    """Verifies that a cited trade ID not present in allowed_trade_ids is rejected."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()
    narrative["habits"][0]["explanation"] = "Flagged trade P9999 cost ₹97,841.20."

    report = verify_narrative(narrative, facts)
    assert report.passed is False
    assert any(f["kind"] == "unknown_trade_id" and f["value"] == "P9999" for f in report.failures)


def test_verifier_rejects_unknown_date() -> None:
    """Verifies that an ungrounded ISO date is rejected."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()
    narrative["habits"][0]["explanation"] = "On date 2025-12-31 you held trade P0010."

    report = verify_narrative(narrative, facts)
    assert report.passed is False
    assert any(f["kind"] == "unknown_date" and f["value"] == "2025-12-31" for f in report.failures)


def test_verifier_tolerance_one_percent_vs_five_percent_off() -> None:
    """Accepts ~1% rounded estimates ('about ₹98,000' for 97,841.20) and rejects 5% off."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()

    # 1. 'about ₹98,000': |98000 - 97841.20| = 158.80, which is 0.16% (< 1%) -> PASSES
    narrative["habits"][0]["explanation"] = (
        "Across winning trades median hold was 21.0 minutes, costing about "
        "₹98,000 across 33 trades."
    )
    report_accept = verify_narrative(narrative, facts)
    ungrounded = [f for f in report_accept.failures if f["kind"] == "ungrounded_number"]
    assert len(ungrounded) == 0

    # 2. '₹103,000': |103000 - 97841.20| = 5158.80, which is ~5.3% (> 1%) -> REJECTED
    narrative["habits"][0]["explanation"] = (
        "Across winning trades median hold was 21.0 minutes, costing about "
        "₹103,000 across 33 trades."
    )
    report_reject = verify_narrative(narrative, facts)
    assert report_reject.passed is False
    assert any(
        f["kind"] == "ungrounded_number" and f["value"] == 103000.0 for f in report_reject.failures
    )


def test_verifier_indian_and_western_grouping_both_parse() -> None:
    """Verifies that 1,48,573 (Indian) and 148,573 (Western) both parse and match 148573.45."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()

    # Indian grouping
    narrative["summary"] = "Impacted by 2 habits with ₹1,48,573 total cost."
    rep1 = verify_narrative(narrative, facts)
    assert not any(f["kind"] == "ungrounded_number" for f in rep1.failures)

    # Western grouping
    narrative["summary"] = "Impacted by 2 habits with ₹148,573 total cost."
    rep2 = verify_narrative(narrative, facts)
    assert not any(f["kind"] == "ungrounded_number" for f in rep2.failures)


def test_verifier_lakh_and_k_suffixes_convert() -> None:
    """Verifies that '1.5 lakh' converts to 150,000 and '98k' converts to 98,000."""
    facts = _make_dummy_facts()
    # Add 150000 to allowed numbers to test '1.5 lakh' matching
    facts["allowed_numbers"].append(150000.0)

    narrative = _make_valid_narrative()
    narrative["habits"][0]["explanation"] = (
        "Cost was 98k across 33 trades with 1.5 lakh total exposure."
    )
    report = verify_narrative(narrative, facts)
    assert not any(f["kind"] == "ungrounded_number" for f in report.failures)
    assert 98000.0 in report.checked_numbers
    assert 150000.0 in report.checked_numbers


def test_verifier_percentage_versus_fraction_matching() -> None:
    """Verifies 41.7% matches allowed fraction 0.4167 within 0.5 percentage points."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()
    # 41.7% vs 0.4167 (41.67%) -> diff 0.03 pp <= 0.5 pp
    narrative["habits"][1]["explanation"] = "Flagged trades had 41.7% overlap across 12 trades."
    report = verify_narrative(narrative, facts)
    assert not any(f["kind"] == "ungrounded_number" for f in report.failures)


def test_verifier_approved_rule_numbers_allowed_in_rule() -> None:
    """Verifies that numbers present in approved_rule are accepted in the rule field."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()
    # 30 is in approved_rule and allowed_numbers -> passes
    narrative["habits"][0]["rule"] = "Exit losing positions after 30 minutes."
    report = verify_narrative(narrative, facts)
    assert not any(f["kind"] == "ungrounded_number" for f in report.failures)

    # 45 is NOT in allowed_numbers -> fails
    narrative["habits"][0]["rule"] = "Exit losing positions after 45 minutes."
    report_fail = verify_narrative(narrative, facts)
    assert any(
        f["kind"] == "ungrounded_number" and f["value"] == 45.0 for f in report_fail.failures
    )


def test_verifier_structure_extra_or_missing_habit_keys_fail() -> None:
    """Verifies extra or missing habit keys fail structural verification."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()

    # Missing habit
    narrative_missing = {
        "summary": narrative["summary"],
        "habits": [narrative["habits"][0]],
    }
    rep_missing = verify_narrative(narrative_missing, facts)
    assert rep_missing.passed is False
    assert any(f["kind"] == "structure" and f["field"] == "habits" for f in rep_missing.failures)

    # Extra habit
    narrative_extra = {
        "summary": narrative["summary"],
        "habits": narrative["habits"]
        + [{"key": "overtrading", "explanation": "Extra", "rule": "Rule"}],
    }
    rep_extra = verify_narrative(narrative_extra, facts)
    assert rep_extra.passed is False
    assert any(f["kind"] == "structure" and f["field"] == "habits" for f in rep_extra.failures)


def test_verifier_structure_order_mismatch_fails() -> None:
    """Verifies habits reversed from expected ranking order fail."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()
    narrative["habits"] = [narrative["habits"][1], narrative["habits"][0]]

    report = verify_narrative(narrative, facts)
    assert report.passed is False
    assert any(f["kind"] == "structure" and f["field"] == "habits" for f in report.failures)


def test_verifier_forbidden_phrases_fail_per_family() -> None:
    """Verifies rejection of forbidden phrases across each phrase family."""
    facts = _make_dummy_facts()

    families = [
        ("market will rise tomorrow", "prediction"),
        ("guaranteed profits await you", "guaranteed"),
        ("you should trade more carefully", "recommendation"),
        ("buy call options on Monday", "buy instruction"),
        ("sell put contracts on weekly expiry", "sell instruction"),
        ("our price target is 25000", "price target"),
    ]

    for phrase, family in families:
        narrative = _make_valid_narrative()
        narrative["habits"][0]["explanation"] += f" We note that {phrase}."
        report = verify_narrative(narrative, facts)
        assert report.passed is False, (
            f"Failed to reject forbidden phrase family '{family}': {phrase}"
        )
        assert any(f["kind"] == "forbidden_content" for f in report.failures)


def test_verifier_returns_all_failures_together() -> None:
    """Verifies that multiple distinct violations are all reported together."""
    facts = _make_dummy_facts()
    narrative = _make_valid_narrative()

    # Inject multiple violations:
    # 1. Ungrounded number 99999
    narrative["habits"][0]["explanation"] = "Cost was ₹99,999."
    # 2. Unknown trade ID P7777
    narrative["habits"][0]["explanation"] += " Seen in trade P7777."
    # 3. Unknown date 2099-01-01
    narrative["habits"][0]["explanation"] += " On 2099-01-01."
    # 4. Forbidden phrase 'guaranteed'
    narrative["habits"][0]["explanation"] += " This is guaranteed."

    report = verify_narrative(narrative, facts)
    assert report.passed is False
    failure_kinds = {f["kind"] for f in report.failures}
    assert "ungrounded_number" in failure_kinds
    assert "unknown_trade_id" in failure_kinds
    assert "unknown_date" in failure_kinds
    assert "forbidden_content" in failure_kinds
    assert len(report.failures) >= 4


def test_verifier_unsupported_claim_terms_fail_per_family() -> None:
    """Verifies rejection of unsupported claim terms across each term family."""
    facts = _make_dummy_facts()

    claim_terms = [
        "decay",
        "theta",
        "vega",
        "volatility",
        "implied volatility",
        "IV",
        "premium erosion",
        "time value",
        "sentiment",
        "news",
        "earnings",
        "expiry effect",
    ]

    for term in claim_terms:
        narrative = _make_valid_narrative()
        narrative["habits"][0]["explanation"] += f" This was caused by {term}."
        report = verify_narrative(narrative, facts)
        assert report.passed is False, f"Failed to reject unsupported claim term: {term}"
        assert any(
            f["kind"] == "unsupported_claim" for f in report.failures
        ), f"Missing unsupported_claim failure for term '{term}'"


def test_all_five_templates_pass_verifier_cleanly() -> None:
    """Verifies that templates for all five habits pass verify_narrative without error."""
    from app.llm.templates import generate_template_narrative
    from app.ranking import RankedHabit, RankedResult

    habits = [
        RankedHabit(
            key="holding_losers",
            name="Holding losers",
            flagged_trade_ids=["P0001"],
            estimated_cost_inr=10000.0,
            confidence=1.0,
            metrics={
                "median_winner_hold_min": 20.0,
                "flagged_median_hold_min": 60.0,
                "flagged_count": 5,
            },
            formula_note="",
            attributed_cost_inr=10000.0,
            overlap_share=0.0,
        ),
        RankedHabit(
            key="revenge_trading",
            name="Revenge trading",
            flagged_trade_ids=["P0002"],
            estimated_cost_inr=8000.0,
            confidence=1.0,
            metrics={"avg_gap_minutes": 5.0, "flagged_entries": 4},
            formula_note="",
            attributed_cost_inr=8000.0,
            overlap_share=0.0,
        ),
        RankedHabit(
            key="overtrading",
            name="Overtrading",
            flagged_trade_ids=["P0003"],
            estimated_cost_inr=6000.0,
            confidence=0.8,
            metrics={
                "spike_day_count": 2,
                "avg_trades_on_spike_days": 15.0,
                "median_daily_trades": 5.0,
                "excess_trades": 10,
            },
            formula_note="",
            attributed_cost_inr=6000.0,
            overlap_share=0.0,
        ),
        RankedHabit(
            key="oversizing",
            name="Oversizing",
            flagged_trade_ids=["P0004"],
            estimated_cost_inr=5000.0,
            confidence=1.0,
            metrics={"median_lots": 1.0, "flagged_entries": 3},
            formula_note="",
            attributed_cost_inr=5000.0,
            overlap_share=0.0,
        ),
        RankedHabit(
            key="averaging_down",
            name="Averaging down",
            flagged_trade_ids=["P0005"],
            estimated_cost_inr=4000.0,
            confidence=1.0,
            metrics={"flagged_entries": 3},
            formula_note="",
            attributed_cost_inr=4000.0,
            overlap_share=0.0,
        ),
    ]

    ranked = RankedResult(
        habits=habits,
        total_attributed_cost_inr=33000.0,
        overlaps=[],
        dropped=[],
        material=True,
        reason=None,
        context={
            "n_trades": 100,
            "gross_pnl_inr": -50000.0,
            "gross_loss_inr": 80000.0,
            "win_rate": 0.4,
        },
    )

    from app.narrative import build_facts

    facts = build_facts(ranked, trades=[])
    narrative = generate_template_narrative(ranked)

    report = verify_narrative(narrative, facts)
    assert report.passed is True, f"Template verification failed: {report.failures}"


def test_derived_rules_differ_for_different_traders() -> None:
    """Verifies holding_losers time stop derives from trader's median winner hold (12m vs 90m)."""
    from app.llm.templates import get_approved_rule

    # Trader A: median winner hold 12m -> rounded to nearest 5m is 10m
    rule_a = get_approved_rule("holding_losers", {"median_winner_hold_min": 12.0})
    assert "10 minutes" in rule_a

    # Trader B: median winner hold 90m -> rounded to nearest 5m is 90m
    rule_b = get_approved_rule("holding_losers", {"median_winner_hold_min": 90.0})
    assert "90 minutes" in rule_b

    assert rule_a != rule_b


def test_changing_median_daily_changes_overtrading_cap() -> None:
    """Verifies that overtrading daily cap equals ceil(median_daily_trades) + 1."""
    from app.llm.templates import get_approved_rule

    # Case 1: median_daily = 3.2 -> ceil(3.2) + 1 = 5
    rule_1 = get_approved_rule("overtrading", {"median_daily_trades": 3.2})
    assert "5 completed trades" in rule_1

    # Case 2: median_daily = 6.1 -> ceil(6.1) + 1 = 8
    rule_2 = get_approved_rule("overtrading", {"median_daily_trades": 6.1})
    assert "8 completed trades" in rule_2

    assert rule_1 != rule_2


def test_oversizing_rule_derived_from_trader_median_lots() -> None:
    """Verifies that oversizing rule derives from median_lots with singular/plural lot(s)."""
    from app.llm.templates import get_approved_rule
    from app.narrative import build_facts
    from app.ranking import RankedHabit, RankedResult

    # Trader with median_lots = 1 -> singular "1 lot"
    rule_1 = get_approved_rule("oversizing", {"median_lots": 1.0})
    assert "usual 1 lot instead of increasing it." in rule_1

    # Trader with median_lots = 5 -> plural "5 lots"
    rule_5 = get_approved_rule("oversizing", {"median_lots": 5.0})
    assert "usual 5 lots instead of increasing it." in rule_5

    assert rule_1 != rule_5

    # Verify both pass verifier with their respective facts
    for lots in (1.0, 5.0):
        h = RankedHabit(
            key="oversizing",
            name="Taking an oversized position after a win or loss streak",
            flagged_trade_ids=["P0001"],
            estimated_cost_inr=5000.0,
            confidence=1.0,
            metrics={"median_lots": lots, "flagged_entries": 3},
            formula_note="",
            attributed_cost_inr=5000.0,
            overlap_share=0.0,
        )
        ranked = RankedResult(
            habits=[h],
            total_attributed_cost_inr=5000.0,
            overlaps=[],
            dropped=[],
            material=True,
            reason=None,
            context={
                "n_trades": 50,
                "gross_pnl_inr": -5000.0,
                "gross_loss_inr": 10000.0,
                "win_rate": 0.4,
            },
        )
        facts = build_facts(ranked, trades=[])
        from app.llm.templates import generate_template_narrative

        narrative = generate_template_narrative(ranked)
        report = verify_narrative(narrative, facts)
        assert report.passed is True, f"Failed for median_lots={lots}: {report.failures}"


def test_single_habit_summary_grammar_and_verifier_pass() -> None:
    """Verifies 1-habit summary format '1 habit stood out this month: ...' passes verifier."""
    from app.llm.templates import generate_template_narrative
    from app.narrative import build_facts
    from app.ranking import RankedHabit, RankedResult

    h = RankedHabit(
        key="holding_losers",
        name="Holding losing trades too long",
        flagged_trade_ids=["P0001"],
        estimated_cost_inr=15000.0,
        confidence=1.0,
        metrics={
            "median_winner_hold_min": 20.0,
            "flagged_median_hold_min": 60.0,
            "flagged_count": 5,
        },
        formula_note="",
        attributed_cost_inr=15000.0,
        overlap_share=0.0,
    )
    ranked = RankedResult(
        habits=[h],
        total_attributed_cost_inr=15000.0,
        overlaps=[],
        dropped=[],
        material=True,
        reason=None,
        context={
            "n_trades": 50,
            "gross_pnl_inr": -15000.0,
            "gross_loss_inr": 25000.0,
            "win_rate": 0.4,
        },
    )

    facts = build_facts(ranked, trades=[])
    narrative = generate_template_narrative(ranked)

    expected_summary = (
        "1 habit stood out this month: holding losing trades too long, "
        "with an attributed cost of ₹15,000.00."
    )
    assert narrative["summary"].startswith(expected_summary)
    report = verify_narrative(narrative, facts)
    assert report.passed is True, f"Failed verification: {report.failures}"

