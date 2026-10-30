# TradeMirror

TradeMirror is a post-trade review tool designed for retail Futures & Options (F&O) traders in India. Rather than presenting generic P&L dashboards or ungrounded predictions, TradeMirror deterministically analyzes historical order logs to diagnose the 2–3 specific behavioral habits costing the trader the most money, complete with concrete rupee figures, verifiable trade evidence, and a single actionable rule to follow for the next trading month.

## Privacy Note

Uploads are processed purely in memory and never written to disk or logged. Server-side audit logging records only the request ID, route, HTTP status, execution duration, and row counts. No raw order records, account numbers, or client data ever persist on the server. Client IPs are used only in memory for rate limiting and are not logged or stored.

## Evals

The evaluation harness (`evals/harness.py`, executable via `make eval`) validates detector accuracy, ranking stability, verifier rigor, and system robustness across 590+ generated and committed trading months. Results are committed in `evals/results/results.md` and `evals/results/results.json`.

### What Each Section Proves and What It Does Not

1. **Committed Datasets (Trade-Level Accuracy)**
   - *What it proves*: Across all baseline, single-habit, mixed, and messy datasets, detectors correctly flag planted trade IDs via `entry_order_ids` with high precision and recall. Cost ratios closely match injected losses, and ranks reflect relative impact.
   - *What it does not prove*: Does not guarantee identical precision on real-world broker logs with arbitrary multi-leg option strategies or non-standard execution styles.

2. **Silence on Clean Data (False-Positive Control)**
   - *What it proves*: When trading logs follow disciplined, habit-free execution across 101 clean months, the false-positive rate is 0.0% (target <= 2%). Detectors stay silent and do not fabricate behavioral defects from ordinary market variance.
   - *What it does not prove*: Does not prove that human traders are ever completely free of cognitive bias, or that unmodelled trading mistakes (e.g. execution slippage) are detected.

3. **Detection by Intensity (Dose-Response Sensitivity)**
   - *What it proves*: Detectors reliably identify habits at medium and high intensities (>= 85% detection rate, cost ratios within 0.5–2.0 across 450 simulated months). Documents sensitivity boundaries at low intensity (holding losers and overtrading are weakly detected when signals are faint).
   - *What it does not prove*: Does not prove that real-world retail traders experience trading habits in discrete, stationary intensity tiers.

4. **Combinations (Multi-Habit Interactions & Attribution)**
   - *What it proves*: When 2–3 habits co-occur with overlapping trade sets, proportional overlap attribution prevents double-counting and limits spurious habit detections to <= 10% (achieved ~1.1%). The top-ranked habit reliably identifies the largest financial leak in >80% of months.
   - *What it does not prove*: Does not provide an exact combinatorial game-theoretic attribution, nor does it model psychological compounding between multiple simultaneous emotional states.

5. **Grounding of the Narrative (Hallucination Prevention)**
   - *What it proves*: The narrative verifier strictly enforces grounded facts: 100% of deterministic templates pass self-consistency, 100% of adversarial mutations (tampered rupee amounts, dates, unsupported claims, forbidden words) are rejected, and benign surface variations (Indian numbering, tolerance-safe rounding) pass (>= 90%). Mocked LLM errors, hallucinations, and 500s fall back to verified templates in <= 2 attempts.
   - *What it does not prove*: Does not guarantee that LLM-authored text will always possess literary flair, only that no ungrounded or fabricated statements can ever reach the user.

6. **Robustness (Ingest & Boundary Handling)**
   - *What it proves*: The ingest layer cleans messy real-world order log anomalies (duplicates, rejected orders, missing prices) matching ground-truth warning counts. Boundary and corrupted inputs (header-only, missing price column, binary payloads, >20,000 rows) fail gracefully with client 422 HTTP responses with zero 500 server crashes.
   - *What it does not prove*: Does not add automatic parsing for unrecognised third-party broker exports that diverge from the supported Zerodha format.

7. **Stability (Determinism & Endpoint Parity)**
   - *What it proves*: Pipeline execution is 100% deterministic: repeat runs produce byte-identical facts JSON. The sample endpoint (`/api/sample/{name}`) and the upload endpoint (`/api/analyze`) produce 100% identical habit lists, costs, and rankings.
   - *What it does not prove*: Does not guarantee reproducibility across disparate CPU architectures if floating-point math libraries differ.

8. **Fallback (Zero-Configuration Reliability)**
   - *What it proves*: In the absence of an LLM API key, TradeMirror functions autonomously without network connectivity, generating verified template narratives with exactly 0 outbound HTTP calls.
   - *What it does not prove*: Does not provide customized narrative prose when running in zero-configuration offline mode.

9. **Known Limitations**
   - *Synthetic author parity*: The evaluative datasets were generated by the same author as the detection algorithms.
   - *Forced loss flattery*: Planted habits in the synthetic generator are artificially forced to lose, providing clear signal separation that flatters cost ratios.
   - *Gross P&L lower bound*: Attributed costs exclude brokerage, STT, exchange fees, and taxes, making them strict lower bounds on actual cash lost.
   - *Proportional overlap attribution*: Portfolio overlap is estimated proportionally by trade count rather than an exact combinatorial per-trade attribution.
   - *Confidence semantics*: Confidence scores represent evidence volume and behavioral extremity, not calibrated Bayesian probabilities.

### Running the Evals

To execute the complete evaluation suite across all 590+ trading months:

```bash
make eval
```

Evaluation results will be regenerated and reported in `evals/results/results.md` and `evals/results/results.json`.

## Deployment

TradeMirror is packaged as a single-service container hosting both the FastAPI backend API and the static React production build.

Live URL: https://trademirror-95rw.onrender.com
Code: https://github.com/adnan011-gif/trademirror
Note: the app runs on Render's free tier. After a period of inactivity the first
request can take 30 to 60 seconds while the server wakes up.
Prompts used to build it: PROMPTS.md
Evals and results: evals/results/results.md

### Deploying on Render (Step-by-Step)

1. **Create Web Service**:
   - In the [Render Dashboard](https://dashboard.render.com/), click **New +** and select **Web Service**.
   - Connect your GitHub repository (`trademirror`).
2. **Select Runtime & Plan**:
   - Environment / Runtime: **Docker**.
   - Plan: **Free**.
   - Render will automatically discover and use `render.yaml` and `Dockerfile`.
3. **Configure Environment Variables**:
   - `TRUST_PROXY`: `true` (configured in `render.yaml` for reverse proxy header handling).
   - `TRUSTED_PROXY_HOPS`: `1` (configured in `render.yaml`).
   - *(Optional)* LLM Narrative Enhancement:
     - `LLM_PROVIDER`: `anthropic` or `openai` (default is `none`).
     - `LLM_MODEL`: `claude-3-5-sonnet-latest` or `gpt-4o-mini`.
     - `LLM_API_KEY`: Your secret API key (marked `sync: false` in `render.yaml`, set manually in dashboard).
   - **Zero-Key Default**: `LLM_PROVIDER=none` is the default setting. TradeMirror is fully functional without any external LLM keys or network dependencies, generating verified, deterministic template narratives.
4. **Deploy**:
   - Click **Create Web Service**.
   - Health checks automatically monitor `/api/health`.
