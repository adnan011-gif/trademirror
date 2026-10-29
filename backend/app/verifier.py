"""Grounding Verifier module for TradeMirror narrative layer.

Responsibility:
Verifies that all numerical values, monetary figures, dates, and trade IDs cited within
generated narrative explanations strictly ground to the computed facts and allowed sets.
Rejects ungrounded figures, hallucinated totals, unknown trade IDs, structural errors,
or forbidden financial recommendations/predictions.

Limitation:
Numbers written solely as English words (e.g., 'ten', 'three') are not parsed or verified;
the LLM prompt strictly requires digits for all numerical facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Forbidden phrases and recommendation/prediction patterns (case-insensitive)
FORBIDDEN_PHRASES: list[str] = [
    "will rise",
    "will fall",
    "will go up",
    "will go down",
    "guaranteed",
    "you should trade",
    "you should buy",
    "you should sell",
    "you should hold",
    "price target",
    "target price",
    "buy call",
    "buy put",
    "sell call",
    "sell put",
    "buy now",
    "sell now",
    "strong buy",
    "strong sell",
    "financial advice",
    "investment advice",
]

FORBIDDEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(buy|sell)\s+(the\s+)?(dip|rally|nifty|banknifty|stock|shares?|contracts?|calls?|puts?|options?|futures?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(recommend|recommendation|advising|suggest)\s+to\s+(buy|sell|hold)\b",
        re.IGNORECASE,
    ),
]

TRADE_ID_PATTERN = re.compile(r"\bP\d{4}\b")
ISO_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
ORDINAL_PATTERN = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)

# Pattern for currency, numbers, decimals, percentages, multiples, lakh, k
NUM_TOKEN_PATTERN = re.compile(
    r"(?:₹|Rs\.?|INR)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(lakhs?|lacs?|k|%|x)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VerificationReport:
    """Detailed report produced by the narrative verifier."""

    passed: bool
    checked_numbers: list[float]
    checked_trade_ids: list[str]
    failures: list[dict[str, Any]]


def _matches_allowed_number(
    val: float,
    is_pct: bool,
    allowed_numbers: list[float],
) -> bool:
    """Check if a parsed numerical value matches any number in the allowed set."""
    val_abs = abs(val)

    # 1. Percentage check against fraction (e.g. 0.4167 vs 41.7%) within 0.5 pp
    if is_pct:
        for allowed in allowed_numbers:
            # Match fraction scaled to percent (0.4167 -> 41.67)
            if abs(val - (allowed * 100.0)) <= 0.5:
                return True
            # Match directly if allowed was already expressed as a percent
            if abs(val - allowed) <= 0.5:
                return True

    # 2. Standard numeric check within max(1.0, 1% of allowed value)
    for allowed in allowed_numbers:
        allowed_abs = abs(allowed)
        tol = max(1.0, 0.01 * allowed_abs)
        if abs(val - allowed) <= tol or abs(val_abs - allowed_abs) <= tol:
            return True

    return False


def verify_narrative(
    narrative: dict[str, Any],
    facts: dict[str, Any] | Any,
) -> VerificationReport:
    """Verify that all numbers, trade IDs, dates, and structures in narrative are grounded.

    Args:
        narrative: Dict with 'summary' and 'habits' ([{key, explanation, rule}]).
        facts: Facts bundle or dict containing allowed numbers, trade IDs, dates, and habits.

    Returns:
        VerificationReport with passed flag, checked tokens, and failure list.
    """
    failures: list[dict[str, Any]] = []
    checked_numbers: list[float] = []
    checked_trade_ids: list[str] = []

    # Extract facts fields
    if hasattr(facts, "to_dict"):
        facts_dict = facts.to_dict()
    elif isinstance(facts, dict):
        facts_dict = facts
    else:
        facts_dict = facts.__dict__

    allowed_numbers: list[float] = [float(x) for x in facts_dict.get("allowed_numbers", [])]
    allowed_trade_ids: set[str] = set(facts_dict.get("allowed_trade_ids", []))
    allowed_dates: set[str] = set(facts_dict.get("allowed_dates", []))
    expected_habits = facts_dict.get("habits", [])
    expected_keys = [h["key"] for h in expected_habits]

    # --- 1. Structure Verification ---
    summary = narrative.get("summary")
    habits = narrative.get("habits")

    if not isinstance(summary, str):
        failures.append(
            {
                "field": "summary",
                "kind": "structure",
                "value": summary,
                "message": "Narrative 'summary' must be a string",
            }
        )
        summary = ""

    if len(summary) > 300:
        failures.append(
            {
                "field": "summary",
                "kind": "length",
                "value": len(summary),
                "message": f"Summary length ({len(summary)}) exceeds 300 character limit",
            }
        )

    if not isinstance(habits, list):
        failures.append(
            {
                "field": "habits",
                "kind": "structure",
                "value": habits,
                "message": "Narrative 'habits' must be a list",
            }
        )
        habits = []

    actual_keys = [h.get("key") for h in habits if isinstance(h, dict)]
    if actual_keys != expected_keys:
        failures.append(
            {
                "field": "habits",
                "kind": "structure",
                "value": actual_keys,
                "message": (
                    f"Habit keys {actual_keys} do not match expected kept habits "
                    f"{expected_keys} in exact order"
                ),
            }
        )

    # Validate individual habit fields
    for idx, h in enumerate(habits):
        if not isinstance(h, dict):
            failures.append(
                {
                    "field": f"habits[{idx}]",
                    "kind": "structure",
                    "value": h,
                    "message": "Each habit entry must be a dictionary",
                }
            )
            continue

        exp = h.get("explanation", "")
        rule = h.get("rule", "")

        if len(exp) > 400:
            failures.append(
                {
                    "field": f"habits[{idx}].explanation",
                    "kind": "length",
                    "value": len(exp),
                    "message": (
                        f"Habit '{h.get('key')}' explanation length ({len(exp)}) "
                        f"exceeds 400 character limit"
                    ),
                }
            )

        if len(rule) > 250:
            failures.append(
                {
                    "field": f"habits[{idx}].rule",
                    "kind": "length",
                    "value": len(rule),
                    "message": (
                        f"Habit '{h.get('key')}' rule length ({len(rule)}) "
                        f"exceeds 250 character limit"
                    ),
                }
            )

    # --- 2. Text Content Verification (Forbidden phrases, Trade IDs, Dates, Numbers) ---
    all_texts: list[tuple[str, str]] = [("summary", summary)]
    for idx, h in enumerate(habits):
        if isinstance(h, dict):
            k = h.get("key", f"habit_{idx}")
            all_texts.append((f"{k}.explanation", h.get("explanation", "")))
            all_texts.append((f"{k}.rule", h.get("rule", "")))

    for field_name, text in all_texts:
        text_lower = text.lower()

        # Check forbidden phrases
        for phrase in FORBIDDEN_PHRASES:
            if phrase in text_lower:
                failures.append(
                    {
                        "field": field_name,
                        "kind": "forbidden_content",
                        "value": phrase,
                        "message": f"Forbidden phrase '{phrase}' detected in {field_name}",
                    }
                )

        # Check forbidden regex patterns
        for pattern in FORBIDDEN_PATTERNS:
            match = pattern.search(text)
            if match:
                matched_str = match.group(0)
                failures.append(
                    {
                        "field": field_name,
                        "kind": "forbidden_content",
                        "value": matched_str,
                        "message": (
                            f"Forbidden recommendation/prediction pattern '{matched_str}' "
                            f"detected in {field_name}"
                        ),
                    }
                )

        # Check trade IDs
        found_tids = TRADE_ID_PATTERN.findall(text)
        for tid in found_tids:
            checked_trade_ids.append(tid)
            if tid not in allowed_trade_ids:
                failures.append(
                    {
                        "field": field_name,
                        "kind": "unknown_trade_id",
                        "value": tid,
                        "message": f"Trade ID '{tid}' in {field_name} is not in allowed trade IDs",
                    }
                )

        # Check dates
        found_dates = ISO_DATE_PATTERN.findall(text)
        for dt in found_dates:
            if dt not in allowed_dates:
                failures.append(
                    {
                        "field": field_name,
                        "kind": "unknown_date",
                        "value": dt,
                        "message": f"Date '{dt}' in {field_name} is not in allowed dates",
                    }
                )

        # Mask out trade IDs, dates, and ordinals before numerical parsing
        masked = TRADE_ID_PATTERN.sub(" ", text)
        masked = ISO_DATE_PATTERN.sub(" ", masked)
        masked = ORDINAL_PATTERN.sub(" ", masked)

        # Extract and verify all numeric tokens
        for m in NUM_TOKEN_PATTERN.finditer(masked):
            raw_str = m.group(1)
            suffix = (m.group(2) or "").lower()

            try:
                val = float(raw_str.replace(",", ""))
            except ValueError:
                continue

            if suffix in ("lakh", "lakhs", "lac", "lacs"):
                val *= 100000.0
            elif suffix == "k":
                val *= 1000.0

            is_pct = suffix == "%"
            checked_numbers.append(val)

            if not _matches_allowed_number(val, is_pct, allowed_numbers):
                failures.append(
                    {
                        "field": field_name,
                        "kind": "ungrounded_number",
                        "value": val,
                        "message": (
                            f"Number {val:,.2f} ({m.group(0).strip()}) in {field_name} "
                            f"does not match any allowed figure in facts"
                        ),
                    }
                )

    passed = len(failures) == 0
    return VerificationReport(
        passed=passed,
        checked_numbers=checked_numbers,
        checked_trade_ids=checked_trade_ids,
        failures=failures,
    )
