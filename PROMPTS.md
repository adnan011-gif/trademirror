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

## Prompt 3: Ingestion and validation

Step 3: implement ingestion in backend/app/parsers/orders_csv.py, with tests in
backend/tests/test_parsers.py (replace the skipped placeholder). Use the Order model
from app/models.py (extend it only if a field is missing).

SCHEMA
Canonical columns, exactly: order_id, timestamp, symbol, instrument_type, strike,
expiry, side, quantity, lot_size, price, status.
- Missing or extra required columns -> raise IngestError with a message naming the
  missing/unexpected columns. Column order does not matter; header matching is
  case-insensitive and whitespace-trimmed.
- Empty file, or header only -> raise IngestError("no orders found").
- Wrong file type or undecodable bytes -> IngestError with a clear message.

PUBLIC API
parse_orders(source: str | Path | bytes | IO) -> IngestResult
IngestResult has: orders (list[Order], cleaned, sorted ascending by timestamp, ties
broken by order_id), warnings (list[IngestWarning]), and counts (dict with raw_rows,
kept, duplicates, rejected, missing_price, invalid).
IngestWarning has: code, row_number (1-based, excluding header), order_id (if known),
message. Warnings are collected, never raised; one bad row must not crash the parse.

ROW RULES — classify every row exactly once, in this precedence:
1. duplicate: the row is an exact duplicate of an earlier row (all fields equal).
   Keep the first, drop later ones.
2. rejected: status is anything other than COMPLETE (case-insensitive).
3. missing_price: price or quantity missing, empty, non-numeric, or <= 0.
4. invalid: anything else unparseable (bad timestamp, side not BUY/SELL,
   instrument_type not CE/PE, bad strike/lot_size). Message says which field.
A row counted under one rule is never counted again under a later rule.

NORMALIZATION
- timestamps parsed to timezone-aware datetimes; a naive timestamp is assumed IST
  (+05:30) and gets a "assumed_ist" warning (once per file, not per row).
- side and status uppercased; symbol stripped and uppercased; numeric fields to
  float/int; expiry to date.
- Do not mutate or interpret prices beyond parsing.

TESTS
- Each dataset in data/datasets/ parses without error.
- For messy.csv, counts duplicates / rejected / missing_price equal the
  expected_ingest_warnings in its ground-truth JSON. If they do NOT match, do not
  loosen the test: tell me whether the parser or the generator is wrong and why.
- clean.csv: zero warnings, kept == raw_rows.
- Sorting: output is ascending by timestamp even though messy.csv is shuffled.
- Schema errors: missing column, extra column, empty file, header-only file, wrong
  case headers (should succeed).
- Row rules: one test per rule, plus a test that a row matching two rules is counted
  once under the higher-precedence rule.
- Naive timestamps get assumed_ist exactly once.
- Accepts a file path, bytes, and an open file object.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 3: Ingestion and
validation" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, stage only relevant files, commit
with the message "feat(ingest): validation and cleaning with tests", and push to
origin main. Show me `git status` and `git log --oneline -3` afterwards. Never
commit .env, API keys, or node_modules. If tests fail, do not commit; fix first.

Result: worked

## Prompt 4: FIFO round-trip pairing

Step 4: implement pairing in backend/app/pairing.py, with tests in
backend/tests/test_pairing.py (replace the skipped placeholder). Extend the Trade
model in app/models.py as needed.

PUBLIC API
pair_orders(orders: list[Order]) -> PairingResult
PairingResult has: trades (list[Trade], closed round-trips only), open_positions
(list[OpenPosition], anything still open at the end of the data), and anomalies
(list of human-readable strings).

MATCHING RULES
- Position key = (symbol, instrument_type, strike, expiry). Match FIFO within a key.
- A BUY first opens a long; a SELL first opens a short. Opposite-side orders close
  existing lots oldest-first.
- Partial exits: an exit larger than the oldest lot consumes lots in order and emits
  one Trade per matched lot slice, so one SELL can produce several Trades.
  Add-ons (a second BUY while long) create a separate lot, so an exit against two
  lots yields two Trades.
- Position flips: if an order is larger than the open opposite position, close it
  fully and open a new position on the other side with the remainder.
- Gross P&L only (no brokerage, taxes, or charges): long = (exit - entry) * qty,
  short = (entry - exit) * qty. State this in the module docstring.
- Open positions at the end are NOT trades. Report them in open_positions and add an
  anomaly line. They must never feed P&L.

TRADE FIELDS (all required)
trade_id (deterministic: "P0001", "P0002"... assigned after sorting by exit_time,
then entry_time, then entry_order_id), symbol, instrument_type, strike, expiry,
direction (LONG/SHORT), entry_time, exit_time, entry_price, exit_price, quantity,
lot_size, hold_minutes (float), gross_pnl, entry_order_id, exit_order_id,
is_partial_exit (bool), is_add_on (bool: the entry lot was opened while another
lot on the same key was already open), trading_date (IST date of entry).

INVARIANTS (enforce in code where cheap, and in tests)
1. Quantity conservation per key: total opened = total closed + total still open.
2. Cash-flow identity: sum(trade.gross_pnl) + realised value of nothing else =
   sum over matched quantities of (sell price - buy price) * qty. Test this
   independently by recomputing from raw orders.
3. hold_minutes >= 0 and exit_time >= entry_time for every trade.
4. No trade has quantity <= 0.
5. Pairing is deterministic: same orders in, identical output (ids and order).
6. Orders arriving unsorted are handled (sort internally by timestamp, order_id).

TESTS
- Simple round trip (hand-computed P&L).
- Partial exit: BUY 150, SELL 50, SELL 100 -> two trades, second not partial.
- One SELL closing two separate lots (add-on case) -> two trades with correct
  per-lot entry prices; check is_add_on.
- Short-then-cover.
- Position flip: long 100, SELL 250 -> closes the long, opens a short of 150.
- Open position at month end -> in open_positions, absent from trades, anomaly
  present.
- Interleaved scrips: orders for three keys mixed together pair independently.
- Determinism and unsorted-input tests.
- GROUND-TRUTH TESTS against data/datasets + data/ground_truth, after parsing with
  parse_orders:
  a) every dataset: invariants 1-4 hold, and open_positions is empty (the
     generator closes everything).
  b) for each habit with planted: true, every entry_order_id and exit_order_id in
     the ground truth appears in some paired Trade's entry_order_id/exit_order_id.
  c) clean.csv: the number of paired trades equals the number of generator trades.
  d) single_averaging_down.csv: every ground-truth add-on entry order maps to a
     Trade with is_add_on = true.
  If any of these fail, do not loosen the test: tell me whether the pairing logic
  or the generator's ground truth is wrong, with the specific order IDs.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 4: FIFO round-trip
pairing" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, stage only relevant files, commit
with the message "feat(pairing): FIFO round-trip trade matching", and push to
origin main. Show me `git status` and `git log --oneline -3` afterwards. Never
commit .env, API keys, or node_modules. If tests fail, do not commit; fix first.
What to check after it runs
Recompute one trade by hand. Pick a trade from clean.csv, find its two orders, and check that (exit - entry) * quantity equals gross_pnl.
Look at the averaging-down case. In single_averaging_down.csv, find a position with two buys and one sell. Confirm that it produced two Trades and that the add-on one is flagged.
Make sure the ground-truth tests actually ran. They should be passing tests, not skipped ones. Ask Antigravity how many parametrized cases ran if the count looks low.
The commit message should be exactly feat(pairing): FIFO round-trip trade matching.

Result: worked
