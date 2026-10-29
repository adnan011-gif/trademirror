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

## Prompt 5a: holding_losers detector

Step 5a: implement ONLY the holding_losers detector in
backend/app/detectors/holding_losers.py, with tests in
backend/tests/test_detectors.py (keep that file organised per detector so later
steps append sections).

FIRST, before writing code: in your plan, tell me what changed in data/generator.py
in the last commit, and whether any committed dataset or ground-truth file other
than messy.* changed as a result. If others changed, list them.

DEFINITION
Habit: the trader holds losing trades far longer than winning trades.
Detector: class HoldingLosersDetector(BaseDetector), key "holding_losers", returning
HabitResult | None. Uses gross_pnl only (state in the docstring that charges are
excluded). Trades with gross_pnl == 0 are neither winners nor losers.

FORMULA (document in the docstring; thresholds as named module constants)
1. winners = trades with pnl > 0; losers = trades with pnl < 0.
   Require len(winners) >= MIN_WINNERS (5) and len(losers) >= MIN_LOSERS (5),
   otherwise return None.
2. median_winner_hold = median hold_minutes of winners.
3. flagged = losers with hold_minutes > HOLD_MULTIPLE (2.0) * median_winner_hold.
4. Effect-size guard (to avoid firing on noise): return None unless
   len(flagged) >= MIN_FLAGGED (3) AND the median hold of losers >=
   MEDIAN_RATIO_MIN (1.5) * median_winner_hold.
5. baseline_loss = median |pnl| of NON-flagged losers; if there are fewer than 3
   non-flagged losers, use the median |pnl| of all losers.
6. estimated_cost_inr = sum over flagged losers of max(0, |pnl| - baseline_loss).
   (Meaning: the extra loss beyond what this trader loses on a normal losing trade.)
   If the total is <= 0, return None.
7. confidence in [0, 1]: min(1, len(flagged) / 10) * min(1, (median_loser_hold /
   median_winner_hold - 1) / 2). Document it plainly.
8. HabitResult fields: key "holding_losers"; name "Holding losing trades too long";
   flagged_trade_ids (Trade.trade_id values, sorted); estimated_cost_inr rounded to
   2 decimals; confidence rounded to 2; metrics = {n_winners, n_losers,
   median_winner_hold_min, median_loser_hold_min, hold_ratio, flagged_count,
   baseline_loss_inr}; formula_note = one plain-English paragraph a trader could
   read, stating the numbers used.
Partial-exit slices are treated as separate trades; say so in a docstring comment.
Keep the thresholds in named constants. Do not tune them on mixed.csv.

TESTS
Unit tests with hand-built Trade lists (hand-compute expected cost):
- fires on a constructed case; exact cost, flagged ids, and metrics asserted
- None when fewer than 5 winners, and when fewer than 5 losers
- None when losers are held about as long as winners
- None when flagged count < 3, and when the median ratio < 1.5
- fewer than 3 non-flagged losers uses the all-losers baseline
- zero-pnl trades are ignored
- cost never negative; result is deterministic

DATASET TESTS (parse_orders -> pair_orders -> detect):
- clean.csv: returns None (assert).
- single_holding_losers.csv and mixed.csv: fires (assert). For
  single_holding_losers compute against ground truth, mapping flagged trades to
  entry_order_ids: precision >= 0.8 and recall >= 0.6. Print precision, recall,
  estimated cost, and ground-truth injected_loss_inr for both datasets.
- Cost sanity: assert estimated_cost is within 0.5x to 2.0x of the ground-truth
  injected_loss_inr on single_holding_losers. If it is outside that band, do NOT
  widen it: report the numbers and tell me whether the formula or the generator's
  injected_loss_inr is the problem.
- The other single_* datasets: do not assert. Print whether the detector fires on
  each and report it to me.

MULTI-SEED ROBUSTNESS (not committed as files): use the generator's functions to
build 30 clean-trader months with seeds different from the committed one, run the
full pipeline in memory, and assert the detector fires on at most 1 of the 30. Also
generate 30 months with holding_losers planted at medium intensity and report the
fraction detected (assert >= 0.8). If the generator lacks a callable for this, add
a small public function that returns (orders, ground_truth) for a seed and config,
without changing existing outputs. Confirm `make data` still reproduces
byte-identical committed files.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 5a: holding_losers
detector" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, stage only relevant files, commit
with the message "feat(detectors): holding_losers", and push to origin main. Show
me `git status` and `git log --oneline -3` afterwards. Never commit .env, API keys,
or node_modules. If tests fail, do not commit; fix first.
What to check after it runs
Its report on the generator change. Only messy.* should have changed. If other datasets changed, ask why before accepting.
The printed precision, recall, and cost numbers. These are what you’ll quote in your evals and interview, so write them down.
The multi-seed results. The clean month should fire at most once in 30, and the planted month should be detected in at least 24 of 30. If either fails, the thresholds need revisiting, not the test.
The other single-habit datasets. Note which ones, if any, trigger holding_losers. A revenge-trading month can legitimately produce long-held losers as a side effect, so a hit there isn’t necessarily a bug, but you should know about it.

Result: worked

## Prompt 5b: revenge_trading detector

Step 5b: implement ONLY the revenge_trading detector in
backend/app/detectors/revenge_trading.py. Append a new section to
backend/tests/test_detectors.py; do not touch the holding_losers section.

RULE FOR THIS STEP (important): the thresholds below are fixed. If a test or the
multi-seed run fails, do NOT change a threshold or loosen a test. Stop, report the
numbers and your diagnosis (detector logic, threshold design, or generator), and
let me decide. Record any such report in the Result line of PROMPTS.md.

DEFINITION
Habit: after a losing trade, the trader jumps back in quickly with a bigger
position.
Detector: class RevengeTradingDetector(BaseDetector), key "revenge_trading",
returning HabitResult | None. Gross P&L only (state in the docstring).

DEFINITIONS USED BY THE FORMULA (document in the docstring)
- Closing event: all Trade slices sharing the same exit_order_id, treated as ONE
  event with pnl = sum of slice pnls, quantity = sum of slice quantities, exit_time
  = their exit_time.
- Entry event: all Trade slices sharing the same entry_order_id, treated as one
  entry with quantity = sum, entry_time = their entry_time. Skip any entry that is
  an add-on (is_add_on = true); those belong to the averaging_down detector.
- Prior event for an entry = the closing event with the latest exit_time that is
  <= the entry's entry_time (ties broken by exit_order_id). If none, the entry is
  ignored.

FORMULA (named module constants)
1. An entry is FLAGGED when all hold:
   a) prior event pnl < 0
   b) 0 <= entry_time - prior exit_time <= WINDOW_MINUTES (15)
   c) entry quantity >= SIZE_MULTIPLE (1.5) * prior event quantity
2. Require len(flagged entries) >= MIN_FLAGGED (3), else return None.
3. flagged_trade_ids = the Trade.trade_id of every slice belonging to a flagged
   entry, sorted.
4. estimated_cost_inr = max(0, -(sum of gross_pnl over those slices)). This is the
   NET loss on revenge trades, so winners among them offset losers. If it is 0,
   return None.
5. confidence = min(1, flagged_entries / 8), rounded to 2.
6. metrics = {eligible_entries (entries whose prior event was a loss within the
   window, regardless of size), flagged_entries, avg_size_multiple (mean of entry
   qty / prior qty over flagged), avg_gap_minutes, flagged_net_pnl_inr,
   revenge_win_rate (share of flagged entries that were profitable)}.
7. name "Re-entering fast after a loss with a bigger size"; formula_note = a plain
   paragraph a trader can read with the actual numbers filled in.

TESTS
Hand-built Trade lists with hand-computed expectations:
- fires on a constructed case: exact cost, ids, metrics
- None when the gap is 16 min, when size is 1.49x, when the prior trade was a win,
  when flagged < 3
- boundary: exactly 15 min and exactly 1.5x count as flagged
- multi-slice closing event is aggregated (prior qty and pnl are sums)
- add-on entries are skipped
- entry with no prior event is ignored
- net cost can go to zero or negative -> None
- determinism

DATASET TESTS (parse_orders -> pair_orders -> detect):
- clean.csv: None
- single_revenge_trading.csv: fires; map flagged entries to ground-truth
  entry_order_ids; assert precision >= 0.8 and recall >= 0.6; assert the cost is
  within 0.5x to 2.0x of injected_loss_inr. Print precision, recall, estimated cost,
  injected_loss_inr, and tell me exactly what the generator's injected_loss_inr
  measures for this habit so we know the comparison is like-for-like.
- mixed.csv: fires; print precision/recall and cost versus ground truth. Also print
  how many flagged trade ids overlap with holding_losers flags on mixed.csv.
- Other single_* datasets: do not assert. Print whether it fires on each.

MULTI-SEED (in memory, using the existing generate_dataset_in_memory): 30 clean
months with new seeds -> assert it fires on at most 1; 30 months with
revenge_trading planted at medium -> assert detection >= 0.8. Print both fractions.
Confirm `make data` still reproduces byte-identical committed files.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 5b: revenge_trading
detector" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, stage only relevant files, commit
with the message "feat(detectors): revenge_trading", and push to origin main. Show
me `git status` and `git log --oneline -3` afterwards. Never commit .env, API keys,
or node_modules. If tests fail, do not commit; fix first.

Result: worked

## Prompt 5c: overtrading detector

Step 5c: implement ONLY the overtrading detector in
backend/app/detectors/overtrading.py. Append a new section to
backend/tests/test_detectors.py; do not touch the earlier sections.

RULE FOR THIS STEP (same as 5b): the thresholds below are fixed. If a test or the
multi-seed run fails, do NOT change a threshold or loosen a test. Stop, report the
numbers and your diagnosis (detector logic, threshold design, or generator), and
let me decide. Record any such report in the Result line of PROMPTS.md. In your
final summary, state explicitly whether any threshold or existing test was changed.

PRELUDE (diagnostic only, no code changes to revenge_trading.py): on mixed.csv, list
the revenge_trading flagged trade ids that are NOT in the ground truth, and for each
say in one line why it was flagged (prior trade, gap, size ratio, and whether the
prior trade was itself a planted holding_losers trade). Tell me whether these look
like genuine accidental matches or a detector flaw.

DEFINITION
Habit: on some days the trader takes far more trades than they normally do.
Detector: class OvertradingDetector(BaseDetector), key "overtrading", returning
HabitResult | None. Gross P&L only. State in the docstring that real overtrading
cost also includes brokerage and charges, which we do not model, so this estimate is
a lower bound.

DEFINITIONS USED BY THE FORMULA (document in the docstring)
- Entry event: all Trade slices sharing the same entry_order_id, treated as ONE trade
  taken. Skip add-ons (is_add_on = true); they belong to averaging_down.
- Day = Trade.trading_date (IST date of entry).
- daily_count[day] = number of entry events that day. Only days with at least one
  entry appear.

FORMULA (named module constants)
1. Require at least MIN_DAYS (10) distinct days, else return None.
2. median_daily = median of daily_count over all days present.
3. A day is a SPIKE DAY when daily_count > SPIKE_MULTIPLE (2.0) * median_daily
   (strictly greater).
4. Require at least MIN_SPIKE_DAYS (2) spike days, else return None.
5. keep_n = ceil(median_daily). On each spike day, order that day's entry events by
   (entry_time, entry_order_id); the first keep_n are normal, the rest are EXCESS.
6. flagged_trade_ids = Trade.trade_id of every slice belonging to an excess entry,
   sorted.
7. estimated_cost_inr = max(0, -(sum of gross_pnl over flagged slices)). Net loss,
   so winning excess trades offset losing ones. If 0, return None.
8. confidence = min(1, spike_days / 4), rounded to 2.
9. metrics = {n_days, median_daily_trades, spike_days (list of ISO dates, sorted),
   spike_day_count, excess_trades, excess_net_pnl_inr, excess_win_rate,
   avg_trades_on_spike_days}.
10. name "Taking far more trades than usual on some days"; formula_note = one plain
    paragraph with the actual numbers filled in.

TESTS
Hand-built Trade lists with hand-computed expectations:
- fires on a constructed case: exact spike days, excess ids, cost, metrics
- exactly 2.0x median is NOT a spike; 2.0x + 1 trade is
- None when fewer than 10 days; None when only 1 spike day
- median with an even number of days; ceil on a fractional median sets keep_n
- excess selection is by entry_time order (earliest are normal)
- multi-slice entry counts as one trade taken
- add-on entries are not counted
- net positive excess P&L -> None
- determinism

DATASET TESTS (parse_orders -> pair_orders -> detect):
- clean.csv: None
- single_overtrading.csv: fires. Evaluate at TWO levels and print both:
  a) day level: flagged spike days vs ground-truth planted days (derive planted days
     from the ground-truth trade/order ids). Assert precision >= 0.8, recall >= 0.6.
  b) trade level: flagged trade ids mapped to entry_order_ids vs ground-truth
     entry_order_ids. Print precision and recall; do NOT assert, but explain any gap
     (for example the generator marking different trades as "excess" than the
     detector's keep-the-earliest rule). Also print the detector's excess count
     against the ground-truth excess count.
  c) cost within 0.5x to 2.0x of injected_loss_inr. Print both and tell me exactly
     what injected_loss_inr measures for this habit, and whether the generator made
     excess trades lose by construction.
- mixed.csv: fires; print day-level and trade-level numbers, plus overlap of flagged
  ids with holding_losers and revenge_trading flags.
- Other single_* datasets: do not assert. Print whether it fires on each.

MULTI-SEED (in memory, via generate_dataset_in_memory): 30 clean months with fresh
seeds (not 700-729 or 800-829) -> assert it fires on at most 1; 30 months with
overtrading planted at medium -> assert detection >= 0.8. Print both fractions.
Confirm `make data` still reproduces byte-identical committed files.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 5c: overtrading
detector" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, stage only relevant files, commit
with the message "feat(detectors): overtrading", and push to origin main. Show me
`git status` and `git log --oneline -3` afterwards. Never commit .env, API keys, or
node_modules. If tests fail, do not commit; fix first.

Result: worked

## Prompt 5c-fix: audit and lots fix

Step 5c-fix. RULE (same as before): do NOT change any threshold or loosen any
assertion. If something unexpected comes up, stop and report numbers and diagnosis
instead of adjusting. In your final summary, list every file you changed and every
existing test you had to edit, with the reason.

PART A: AUDIT (read-only, report before changing anything)
1. Run `git show --stat b160836 -- data/`. List every file under data/datasets and
   data/ground_truth whose bytes changed in that commit. For any file other than
   those belonging to single_overtrading and mixed (and messy if relevant), explain
   why it changed. In particular tell me whether clean.csv or clean.json changed.
2. Describe in plain words what each intensity level (low / medium / high) now means
   in generator.py for overtrading (number of spike days, trades per spike day).
3. On the CURRENT committed datasets, re-run and print precision, recall, and cost
   for holding_losers (single_holding_losers, mixed) and revenge_trading
   (single_revenge_trading, mixed), noting which numbers moved and why.

PART B: FIX (compare size in lots, not raw quantity)
1. Add a small shared helper (in app/models.py or detectors/base.py) returning
   position size in LOTS (quantity / lot_size) for a Trade, and a helper to
   aggregate a group of slices into lots. Use it in revenge_trading.py ONLY for size
   condition (c): entry_lots >= SIZE_MULTIPLE (1.5) * prior_event_lots. Keep
   threshold 1.5. Update docstring, metrics (avg_size_multiple in lots), and
   formula_note.
2. Add tests: (a) 1 lot BANKNIFTY loss followed within window by 1 lot NIFTY is NOT
   flagged; (b) NIFTY 1 lot loss then NIFTY 2 lots is flagged; (c) 2 lots then 3
   lots (1.5x) is flagged; (d) same-instrument lots behave identically to old
   raw-quantity behavior. Edit fixtures only if existing tests lacked a lot_size.
3. Re-run on mixed.csv (expecting P0074, P0079, P0105 to disappear) and print
   precision, recall, flagged IDs; re-run single_revenge_trading and print
   precision/recall/cost.
4. Multi-seed (in memory, fresh seeds 860-889 clean -> at most 1 fires; seeds 890-919
   revenge_trading medium -> >= 0.8 detection). Stop if planted detection drops or
   single_revenge recall falls below 0.6.
5. Confirm `make data` reproduces byte-identical committed files.

Update PROMPTS.md: append prompt verbatim as "## Prompt 5c-fix: audit and lots fix"
with a "Result:" line.
Git: stage relevant files, commit with message "fix(detectors): compare position size
in lots, not raw quantity", push to origin main, and show git status and git log
--oneline -3.

Result: All checks passed. PART A: Only single_overtrading.*, mixed.*, messy.* changed in b160836; clean.* unchanged. Intensity: low=2 spike days, medium=3, high=5, each targets >=12 trades/day. holding_losers: precision=1.0/recall=1.0 on both datasets. revenge_trading single: precision=1.0/recall=0.923; mixed before fix: precision=0.75/recall=0.692 with FPs P0082/P0087/P0113 (cross-instrument 1-lot each). PART B: Added Trade.trade_lots property and aggregate_lots() to models.py; switched revenge_trading.py size comparison to lots. 5 new tests in Section 2b all pass. After fix mixed: FPs gone, precision/recall both improved. Multi-seed: clean 0/30 fires, planted 30/30 fires (100%). make data byte-identical.

