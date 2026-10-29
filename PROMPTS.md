## Prompt 0: Project brief

You are a senior full-stack engineer. We are building "TradeMirror", a post-trade
review tool for retail F&O traders in India. It turns a month of order history into
the 2-3 behavioural habits that cost the trader the most money.

Product rules (these govern every decision):
- Output is 2-3 habits, never a dashboard. Each habit has: name, estimated rupee
  cost, evidence (specific trade IDs), a plain-language explanation, and ONE
  concrete rule the trader can follow next month.
- All numbers come from deterministic Python code. The LLM never calculates; it
  only explains numbers it is given.
- Every claim in the narrative must be traceable to a computed number or trade ID.
- Out of scope: live broker integration, tax/P&L reports, predictions, trade
  recommendations.

Tech: Python 3.11, FastAPI, pandas, pytest; React + Vite + TypeScript frontend;
LLM calls through a single wrapper module with a deterministic template fallback
when no API key is set.

Deployment architecture: SINGLE SERVICE. FastAPI serves the built React app from
/frontend/dist at "/", and all API routes live under "/api". The frontend calls
relative paths (/api/...), so there is no CORS and no second host. One multi-stage
Dockerfile builds the frontend, then runs the backend.

Git workflow: this repo is connected to GitHub (origin). After each step, once code
runs and tests pass, commit with a conventional-commit message and push to main.
Never commit secrets (.env, API keys). Keep commits small and one per step.

Prompt log: maintain /PROMPTS.md in the repo. I will paste each prompt I send you;
append it verbatim under a numbered heading, and note in one line whether it worked
or needed a retry. Do not edit or clean up my prompts.

Working style: small modules, type hints, docstrings on every detector explaining
the formula, no dead code. Before each step, state your plan in 5 lines max. Wait
for my next prompt before starting the next step.

Confirm you understand and propose the folder structure. Do not write code yet.

Result: worked

## Prompt 0b: Structure correction

Structure approved with these changes. Please apply them and re-print the tree
before writing any code:

1. Add backend/app/pairing.py (FIFO round-trip trade matching; Trade model lives
   in app/models.py).
2. Add backend/app/verifier.py (grounding checks on narrative numbers and trade
   IDs).
3. Add /data (synthetic generator + datasets + ground-truth JSON), /evals
   (harness + results), and /prompts (narrative_system.md).
4. Detectors: five, each in its own file under app/detectors/:
   holding_losers.py, revenge_trading.py, overtrading.py, oversizing.py,
   averaging_down.py. Keep ranking.py in app/ (not inside detectors/).
   - holding_losers = losers held longer than winners ONLY. No "cutting winners
     early".
   - revenge_trading = re-entry within 15 minutes of a losing close, size >= 1.5x.
   - oversizing = size > 2x median after a 2+ win or loss streak. These two must
     not overlap in definition.
5. Endpoints: POST /api/analyze, GET /api/sample/{name}, GET /api/health only. No
   /api/upload.
6. Keep pyproject.toml (not requirements.txt) and add a Makefile with
   run-backend, run-frontend, build, test, eval targets.
7. Parser scope: one canonical CSV schema (order_id, timestamp, symbol,
   instrument_type, strike, expiry, side, quantity, lot_size, price, status). No
   multi-broker support. Rename broker_csv.py to orders_csv.py.

Keep everything else as proposed. Do not write code yet.

Result: worked

## Prompt 1: Scaffold

Structure approved exactly as printed. Now create the scaffold for that tree, with
STUBS ONLY: no business logic yet. Each module gets a docstring stating its
responsibility and the minimal signatures/classes that later steps will fill in.

Specifics:
- pyproject.toml: Python 3.11; dependencies fastapi, uvicorn[standard], pandas,
  pydantic, pydantic-settings, python-multipart, httpx; dev extras pytest,
  pytest-cov, ruff. Configure pytest (testpaths = backend/tests, pythonpath =
  backend) and ruff.
- backend/app/config.py: pydantic-settings Settings with LLM_API_KEY (optional),
  LLM_MODEL, MAX_UPLOAD_MB, loaded from .env.
- backend/app/main.py: FastAPI app, router included under the /api prefix. For now
  it only exposes GET /api/health returning {"status": "ok"}. Do not add static
  mounting yet.
- backend/app/models.py: dataclasses for Order, Trade, Habit with the fields from
  the plan; no methods yet.
- backend/app/detectors/base.py: BaseDetector (abstract detect(trades) -> HabitResult
  | None) and HabitResult dataclass (key, name, flagged_trade_ids,
  estimated_cost_inr, confidence, metrics, formula_note).
- All other modules: docstring + TODO-free empty skeletons only.
- backend/tests/test_api.py: one real test for /api/health. Other test files can
  contain a single skipped placeholder test each.
- frontend: Vite + React + TypeScript scaffold. vite.config.ts proxies /api to
  http://localhost:8000 in dev. App.tsx renders a minimal page that calls
  /api/health and shows the result. Create the component and service files from the
  tree as empty typed stubs.
- Makefile: run-backend, run-frontend, build (npm run build), test, eval (placeholder
  that echoes "not implemented").
- .gitignore: .env, .venv, node_modules, __pycache__, .pytest_cache, .ruff_cache,
  frontend/dist, .DS_Store.
- .env.example: LLM_API_KEY=, LLM_MODEL=, MAX_UPLOAD_MB=5
- README.md: title and a one-paragraph problem statement only (we'll expand later).
- PROMPTS.md: create it with these entries, verbatim, in order:
    "## Prompt 0: Project brief" (paste the brief I sent), "## Prompt 0b: Structure
    correction" (paste my correction message), and "## Prompt 1: Scaffold" (this
    message). After each, add one line: "Result: worked" or "Result: needed retry
    (reason)". Do not rewrite or tidy the prompts.

Verify: `make test` passes, the backend starts and /api/health responds, the
frontend dev server starts and shows the health result through the proxy, and
`npm run build` succeeds.

GIT: initialize git, set the default branch to main, add the remote
https://github.com/<adnan011-gif>/trademirror.git, stage only relevant files,
commit with the message "chore: scaffold backend, frontend, tooling", and push to
origin main. Show me `git status` and `git log --oneline -3` afterwards. Never
commit .env, API keys, or node_modules. If tests fail, do not commit; fix first.

Result: worked

## Prompt 2: Synthetic data generator

Step 2: build the synthetic data generator. This is the foundation for our evals,
so determinism and ground-truth accuracy matter more than realism.

Files: data/generator.py, data/datasets/, data/ground_truth/,
backend/tests/test_generator.py. Update pyproject.toml so pytest can import the
`data` package (pythonpath = ["backend", "."]) and add data/__init__.py.

DESIGN
- Generate TRADES first (entry + exit), then emit ORDERS from them. Each trade has
  a stable trade_id (T0001...), entry_order_id and exit_order_id.
- Long-only option buying (BUY to open, SELL to close) on NIFTY and BANKNIFTY CE/PE.
  Lot sizes are named constants (NIFTY=75, BANKNIFTY=35, illustrative). quantity =
  lots * lot_size.
- One fixed trading month, weekdays only, timestamps in IST (+05:30) between 09:15
  and 15:30. Use a seeded random.Random; never use global randomness or the wall
  clock.
- Output CSV columns exactly: order_id, timestamp, symbol, instrument_type, strike,
  expiry, side, quantity, lot_size, price, status. status = COMPLETE for normal rows.
- P&L comes from price paths: entry premium 40-250, exit premium = entry * (1 +
  return), returns drawn from a distribution giving ~45-55% win rate.

BASELINE ("clean" trader) must NOT trigger any detector by construction:
- 3-6 trades per day (never above ~1.5x the monthly median)
- fixed 1-2 lots, with no size jump above 1.5x the median and none tied to streaks
- hold times for winners and losers drawn from the SAME distribution
- at least 45 minutes between a loss and the next entry
- never add to an open position; one position open at a time
Put these constraints in named constants and assert them in a test over clean.csv.

PLANTED HABITS (each takes an intensity: low / medium / high controlling how many
trades are affected) and records affected trades in ground truth:
1. holding_losers: affected losers held >2x the median winner hold time.
2. revenge_trading: after a losing close, re-enter within 15 min with quantity >=
   1.5x the prior trade.
3. overtrading: some days get >2x the median daily count; mark the excess trades.
4. oversizing: after a 2+ trade win or loss streak, next trade quantity >2x median.
5. averaging_down: add a second BUY in the same scrip while the open position is
   below average entry; the add-on entry orders are the flagged ones.

GROUND TRUTH JSON per dataset:
{
  "dataset": "...", "seed": 123,
  "habits": {
    "<habit_key>": {
      "planted": true, "intensity": "medium",
      "trade_ids": [...], "entry_order_ids": [...], "exit_order_ids": [...],
      "injected_loss_inr": <float, the extra loss attributable to the habit>
    }
  },
  "expected_ingest_warnings": {"duplicates": n, "missing_price": n, "rejected": n}
}
Non-planted habits are listed with planted: false so the evals can check silence.

DATASETS (fixed seeds, written to data/datasets/ with matching JSON in
data/ground_truth/):
- clean.csv
- single_holding_losers.csv, single_revenge_trading.csv, single_overtrading.csv,
  single_oversizing.csv, single_averaging_down.csv (each: one habit, medium)
- mixed.csv (holding_losers high, revenge_trading medium, overtrading low)
- messy.csv (a mixed-like base plus: exact duplicate rows, rows with missing price,
  status=REJECTED rows, shuffled timestamp order; record counts in
  expected_ingest_warnings)

CLI: `python -m data.generator --all` regenerates everything; running it twice must
produce byte-identical files. Add a `make data` target.

TESTS (backend/tests/test_generator.py): determinism (same seed, identical output);
schema columns; clean.csv satisfies every baseline constraint; each single dataset
has its planted habit's trade_ids non-empty and all other habits planted:false;
ground-truth trade_ids all exist in the data; messy.csv counts match the recorded
expected_ingest_warnings.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 2: Synthetic data
generator" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `make data` pass, stage only relevant files (including
the generated datasets, which are small), commit with the message
"feat(data): synthetic order generator with planted habits", and push to origin
main. Show me `git status` and `git log --oneline -3` afterwards. Never commit
.env, API keys, or node_modules. If tests fail, do not commit; fix first.

Result: worked
