# TradeMirror Evaluation Report

- **Commit**: `dda021cc5026149bae4f4adfb2217f30faba2e93`
- **Run Date**: 2026-10-30
- **Seed Ranges**: Clean: `2000-2099`, Intensity: `2100-2549`, Combinations: `2600-2639`

## Summary of Targets

- **Section 2: Silence on clean data (kept <= 2%)**: **MET** — 0.0% kept (0/101)
- **Section 3: Detection by intensity (medium/high >= 85%, cost ratio 0.5-2.0)**: **MET** — All medium & high cells within targets
- **Section 4: Combinations (spurious-habit rate <= 10%)**: **MET** — 1.08% spurious rate
- **Section 5a: Template self-consistency (100%)**: **MET** — 100.0% passed (454/454)
- **Section 5b: Adversarial rejection (100%)**: **MET** — 100.0% rejected (33/33)
- **Section 5c: Benign variants acceptance (>= 90%)**: **MET** — 100.0% accepted (16/16)
- **Section 6: Robustness (no 500s on malformed inputs)**: **MET** — All corrupted and boundary inputs handled with client 422 errors
- **Section 7: Stability (100% byte-identical facts & endpoint parity)**: **MET** — Facts: 100%, Endpoints: 100%
- **Section 8: Fallback (zero HTTP calls with no LLM key)**: **MET** — 0 HTTP calls, 100% verified templates

---

## 1. Committed Datasets

| Dataset | Planted Habit | Precision | Recall | Est Cost (₹) | Injected Loss (₹) | Cost Ratio | Conf | Rank |
|---|---|---|---|---|---|---|---|---|
| `clean` | `none (clean)` | 1.00 | 1.00 | ₹0.00 | ₹0.00 | 1.00 | 0.00 | none |
| `single_holding_losers` | `holding_losers` | 1.00 | 1.00 | ₹56,518.88 | ₹51,028.80 | 1.11 | 1.00 | 1 |
| `single_revenge_trading` | `revenge_trading` | 1.00 | 0.92 | ₹87,898.20 | ₹91,213.20 | 0.96 | 1.00 | 1 |
| `single_overtrading` | `overtrading` | 1.00 | 0.78 | ₹34,666.50 | ₹44,886.75 | 0.77 | 0.75 | 1 |
| `single_oversizing` | `oversizing` | 1.00 | 0.95 | ₹130,727.40 | ₹135,033.90 | 0.97 | 1.00 | 1 |
| `single_averaging_down` | `averaging_down` | 1.00 | 1.00 | ₹6,879.95 | ₹8,373.05 | 0.82 | 1.00 | 1 |
| `mixed` | `holding_losers` | 1.00 | 1.00 | ₹97,841.20 | ₹89,628.25 | 1.09 | 0.83 | 1 |
| `mixed` | `revenge_trading` | 1.00 | 0.92 | ₹48,177.00 | ₹52,878.00 | 0.91 | 1.00 | 2 |
| `mixed` | `overtrading` | 0.86 | 1.00 | ₹22,629.00 | ₹24,305.25 | 0.93 | 0.50 | 3 |
| `messy` | `holding_losers` | 1.00 | 1.00 | ₹84,499.65 | ₹94,028.10 | 0.90 | 1.00 | 1 |
| `messy` | `revenge_trading` | 1.00 | 0.92 | ₹58,032.45 | ₹59,243.45 | 0.98 | 1.00 | 2 |
| `messy` | `overtrading` | 1.00 | 0.88 | ₹31,281.75 | ₹39,401.25 | 0.79 | 0.50 | 3 |

## 2. Silence on Clean Data

- **Kept Habit Months**: 0 of 101 (0.00%) [Target: <= 2.0%]
- **Per-Detector Raw Fire Counts** across 101 clean months:
  - `holding_losers`: 0
  - `revenge_trading`: 0
  - `overtrading`: 0
  - `oversizing`: 0
  - `averaging_down`: 0

## 3. Detection by Intensity

- **Weakly Detected at Low Intensity**: holding_losers (23.3%), overtrading (63.3%)

| Habit | Intensity | Detection Rate | Mean Precision | Mean Recall | Median Cost Ratio | Target Met |
|---|---|---|---|---|---|---|
| `holding_losers` | `low` | 23.3% | 0.23 | 0.23 | 0.00 | Report Only |
| `holding_losers` | `medium` | 90.0% | 0.90 | 0.89 | 1.21 | MET |
| `holding_losers` | `high` | 100.0% | 1.00 | 0.99 | 1.10 | MET |
| `revenge_trading` | `low` | 100.0% | 1.00 | 0.98 | 1.00 | Report Only |
| `revenge_trading` | `medium` | 100.0% | 1.00 | 0.95 | 0.99 | MET |
| `revenge_trading` | `high` | 100.0% | 1.00 | 0.92 | 0.93 | MET |
| `overtrading` | `low` | 63.3% | 0.62 | 0.58 | 0.83 | Report Only |
| `overtrading` | `medium` | 86.7% | 0.82 | 0.74 | 0.85 | MET |
| `overtrading` | `high` | 100.0% | 0.98 | 0.82 | 0.80 | MET |
| `oversizing` | `low` | 100.0% | 1.00 | 0.90 | 0.94 | Report Only |
| `oversizing` | `medium` | 100.0% | 1.00 | 0.82 | 0.81 | MET |
| `oversizing` | `high` | 100.0% | 1.00 | 0.76 | 0.77 | MET |
| `averaging_down` | `low` | 90.0% | 0.93 | 0.93 | 0.86 | Report Only |
| `averaging_down` | `medium` | 100.0% | 1.00 | 1.00 | 0.87 | MET |
| `averaging_down` | `high` | 100.0% | 1.00 | 1.00 | 0.86 | MET |

## 4. Combinations (40 Months, 2–3 Habits, Medium/High)

- **Exact-Set Match Rate**: 67.5%
- **Planted-Habit Recall**: 87.6%
- **Spurious-Habit Rate**: 1.08% [Target: <= 10.0%]
- **Top-Ranked Equals Largest Injected Loss**: 82.5%

## 5. Grounding of the Narrative

- **Template Self-Consistency**: 100.0% passed (454/454) [Target: 100%]
- **Adversarial Rejection Rate**: 100.0% rejected (33/33) [Target: 100%]
- **Benign Variants Acceptance**: 100.0% accepted (16/16) [Target: >= 90%]
- **False Rejections**: None

### Scripted LLM Scenarios (Mocked Transport)

| Scenario | Output Source | LLM Attempts | Fallback Reason |
|---|---|---|---|
| `scripted_good_response` | `llm` | 1 | None (Passed) |
| `hallucinated_response` | `template` | 2 | verification_failed |
| `malformed_json` | `template` | 2 | json_parse_error: Expecting value: line 1 column 1 (char 0) |
| `http_500_error` | `template` | 1 | llm_call_error: Server error '500 Internal Server Error' for url 'https://api.anthropic.com/v1/messages' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500 |

## 6. Robustness

| Input Variant | HTTP Status | Detail / Message |
|---|---|---|
| `messy.csv (normal upload)` | 200 | Ingest counts match ground truth: duplicates=3, rejected=4, missing_price=2 |
| `header_only.csv` | 422 | no orders found |
| `missing_price_column.csv` | 422 | Schema mismatch: missing required columns: ['price'] |
| `binary_bytes.bin` | 422 | Invalid file format. Only CSV files (.csv or text/csv) are accepted. |
| `file_with_20001_rows.csv` | 422 | File contains 20002 rows, which exceeds the limit of 20000 rows. |

## 7. Stability

- **Pipeline Facts Byte-Identical Rate**: 100% across 2 runs on all 8 committed datasets [Target: 100%]
- **Sample Endpoint vs Analyze Upload Parity**: 100% across all 8 datasets [Target: 100%]

## 8. Fallback Under Missing LLM Configuration

- **HTTP Calls Made**: 0 [Target: 0]
- **Dataset Verification**:
  - `clean`: source=`template`, verified=`True`
  - `single_holding_losers`: source=`template`, verified=`True`
  - `single_revenge_trading`: source=`template`, verified=`True`
  - `single_overtrading`: source=`template`, verified=`True`
  - `single_oversizing`: source=`template`, verified=`True`
  - `single_averaging_down`: source=`template`, verified=`True`
  - `mixed`: source=`template`, verified=`True`
  - `messy`: source=`template`, verified=`True`

## 9. Known Limitations

1. **Synthetic Author Parity**: Datasets are synthetic and generated by the same codebase author as the detectors. These evaluations prove that the detectors reliably recover what the generator plants, not that real-world retail options traders behave in this exact parametric manner.
2. **Forced Loss Flattery**: Planted loss habits are artificially forced to be losing trades in several generator methods, which guarantees a clean distinction between baseline trades and habit-induced trades, flattering cost ratios.
   - holding_losers: extends hold time specifically for trades already destined to lose, ensuring extended losers have larger losses.
   - revenge_trading: explicitly overrides pnl_inr to a forced negative loss on re-entries following losing trades.
   - overtrading: explicitly forces trades above the daily baseline volume threshold to be losing trades.
   - oversizing: explicitly forces position sizes following two consecutive wins or losses to result in losing trades.
   - averaging_down: samples exclusively from losing positions and injects lower-priced add-on orders that exit at a net loss.
3. **Gross P&L Lower Bounds**: All calculations rely purely on gross P&L (exit price minus entry price times quantity). Brokerage charges, Securities Transaction Tax (STT), exchange turnover fees, and GST are not included. Reported habit costs therefore represent strict lower bounds on the total capital destroyed.
4. **Proportional Overlap Attribution**: Portfolio overlap attribution is computed using a proportional-by-count approximation (attributed_cost_inr = estimated_cost_inr * (1 - overlap_share)), not an exact combinatorial per-trade attribution. This provides a deterministic, transparent adjustment but remains a heuristic approximation.
5. **Confidence Semantics**: Confidence scores reflect evidence volume and behavioral extremity (e.g., hold-time ratios, cooldown violation speed), not a frequentist or Bayesian probability of recurrence.
6. **Threshold Calibration History**:
   - holding_losers 5a: replaced mean ratio with median ratio (flagged_median_hold / median_winner_hold) to ensure resistance to outliers.
   - oversizing: derived position thresholds dynamically from trader's median lot size instead of hardcoded 2 lots.
   - holding_losers confidence: corrected to compare flagged losers' median hold against winning trades rather than all losers.
