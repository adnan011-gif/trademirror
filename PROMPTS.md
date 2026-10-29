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

## Prompt 5d: oversizing detector

Step 5d: implement ONLY the oversizing detector in
backend/app/detectors/oversizing.py. Append a new section to
backend/tests/test_detectors.py; do not touch earlier sections.

RULES: thresholds below are fixed. Do NOT modify data/generator.py in this step. If
a test or multi-seed run fails, STOP and report numbers and diagnosis (detector
logic, threshold design, or generator) and let me decide. If you believe the
generator needs a change, say so and wait. In your final summary state explicitly
whether any threshold, existing test, generator file, or committed dataset was
changed (expected: none).

SIZE UNIT: always LOTS (quantity / lot_size), using the shared helper from 5c-fix.
Never compare raw quantity across instruments.

DEFINITION
Habit: after a run of wins or losses, the trader takes a much bigger position than
usual. Detector: class OversizingDetector(BaseDetector), key "oversizing", returning
HabitResult | None. Gross P&L only (state in the docstring).

DEFINITIONS USED BY THE FORMULA (document in the docstring)
- Entry event: all Trade slices sharing the same entry_order_id as ONE entry; size =
  total lots, pnl = sum of slice pnls. Skip add-ons (is_add_on = true).
- Closing event: all slices sharing the same exit_order_id as one event (pnl = sum).
  Order closing events by (exit_time, exit_order_id).
- Streak before an entry: take the last STREAK_LEN (2) closing events with
  exit_time <= entry_time. It is a streak if all have pnl > 0 (win streak) or all
  have pnl < 0 (loss streak). A zero pnl breaks the streak. Fewer than 2 prior
  closing events means no streak.

FORMULA (named module constants)
1. Require at least MIN_ENTRIES (20) entry events, else return None.
2. median_lots = median size in lots over all entry events.
3. An entry is FLAGGED when size_lots > SIZE_MULTIPLE (2.0) * median_lots (strictly
   greater) AND it follows a streak.
4. Require len(flagged) >= MIN_FLAGGED (3), else return None.
5. flagged_trade_ids = Trade.trade_id of every slice of a flagged entry, sorted.
6. estimated_cost_inr = sum over flagged entries of max(0, -entry_pnl) *
   (1 - median_lots / size_lots). Meaning: the extra loss attributable to the larger
   size, assuming a normal-size trade would have lost proportionally less. Round to
   2 decimals. If the total is <= 0, return None. State in the docstring that this
   assumes P&L scales linearly with size.
7. confidence = min(1, flagged_entries / 8), rounded to 2.
8. metrics = {n_entries, median_lots, flagged_entries, avg_size_multiple,
   after_win_streak, after_loss_streak, flagged_net_pnl_inr, flagged_gross_loss_inr}.
9. name "Betting much bigger after a streak"; formula_note = one plain paragraph a
   trader can read with the actual numbers filled in.

TESTS
Hand-built Trade lists with hand-computed expectations:
- fires on a constructed case: exact cost, ids, metrics
- exactly 2.0x median is NOT flagged; just above is
- big size with no streak is NOT flagged; streak of only 1 is not a streak; mixed
  win/loss pair is not a streak; a zero-pnl trade breaks the streak
- both win-streak and loss-streak cases flag
- same lots on NIFTY (75) and BANKNIFTY (35) are the same size (no flag)
- multi-slice entry aggregated; add-on entries skipped
- fewer than 20 entries -> None; fewer than 3 flagged -> None
- winning flagged entries contribute 0 to cost; all winners -> None
- determinism

DATASET TESTS (parse_orders -> pair_orders -> detect):
- clean.csv: None
- single_oversizing.csv: fires. Map flagged entries to ground-truth entry_order_ids:
  assert precision >= 0.8 and recall >= 0.6; assert cost within 0.5x to 2.0x of
  injected_loss_inr. Print precision, recall, cost, injected_loss_inr, and tell me
  exactly what injected_loss_inr measures for this habit and whether the generator
  forces oversized trades to lose.
- mixed.csv and the other single_* datasets: do not assert. Print whether it fires
  on each, and for any dataset where oversizing is not planted but it fires, list the
  flagged entries and why (this would be a false positive or a habit interaction).
  Also print overlap with the other detectors' flags on mixed.csv.

MULTI-SEED (in memory, via generate_dataset_in_memory): 30 clean months seeds
920-949 -> assert at most 1 fires; 30 months with oversizing planted at medium seeds
950-979 -> assert detection >= 0.8. Print both. Confirm `make data` reproduces
byte-identical committed files.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 5d: oversizing
detector" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, stage only relevant files, commit
with the message "feat(detectors): oversizing", and push to origin main. Show me
`git status` and `git log --oneline -3` afterwards. Never commit .env, API keys, or
node_modules. If tests fail, do not commit; fix first.

Result: worked. Oversizing detector implemented in backend/app/detectors/oversizing.py with fixed thresholds (MIN_ENTRIES=20, SIZE_MULTIPLE=2.0, STREAK_LEN=2, MIN_FLAGGED=3). Single_oversizing.csv: precision=1.000, recall=0.950, cost=₹130,727.40 vs injected=₹135,033.90 (ratio 0.968, within [0.5, 2.0]). Clean.csv and all non-planted single_* datasets and mixed.csv: None (0 false positives). Multi-seed: clean 0/30 fires, planted 30/30 detected (100%). make data byte-identical. 89 tests pass, ruff clean.
## Prompt 5e: averaging_down detector

Step 5e: implement ONLY the averaging_down detector in
backend/app/detectors/averaging_down.py. Append a new section to
backend/tests/test_detectors.py; do not touch earlier sections.

RULES: thresholds below are fixed. Do NOT modify data/generator.py in this step. If a
test or multi-seed run fails, STOP and report numbers and diagnosis (detector logic,
threshold design, or generator) and let me decide. In your final summary state
explicitly whether any threshold, existing test, generator file, or committed dataset
changed (expected: none).

DEFINITION
Habit: the trader adds to a position that is already losing, hoping to average the
price down. Detector: class AveragingDownDetector(BaseDetector), key
"averaging_down", returning HabitResult | None. Gross P&L only (state in docstring).

DEFINITIONS USED BY THE FORMULA (document in the docstring)
- Add-on entry event: all Trade slices sharing the same entry_order_id where
  is_add_on = true, treated as ONE event (qty, pnl = sums; entry_price is the same
  across slices).
- Existing position at the add-on's entry_time: all other slices with the same
  position key (symbol, instrument_type, strike, expiry) and the same direction, with
  entry_time before the add-on's entry_time (ties broken by entry_order_id) AND
  exit_time strictly after the add-on's entry_time. Its average entry =
  quantity-weighted mean of those slices' entry_price. If no such slices exist, the
  add-on is not evaluated.
- UNDERWATER add-on: for LONG, add-on entry_price < existing average entry (strictly);
  for SHORT, add-on entry_price > existing average entry (strictly). Equal price or
  adding to a winner (pyramiding) is NOT flagged.

FORMULA (named module constants)
1. An add-on entry is FLAGGED when it is underwater as defined above.
2. Require len(flagged) >= MIN_FLAGGED (3), else return None.
3. flagged_trade_ids = Trade.trade_id of every slice of a flagged add-on entry, sorted.
4. estimated_cost_inr = max(0, -(sum of gross_pnl over those slices)). Net loss on the
   add-on legs, so winning add-ons offset losing ones. If 0, return None.
5. confidence = min(1, flagged_entries / 6), rounded to 2.
6. metrics = {n_entries (all entry events, add-ons included), add_on_entries (all
   add-ons), flagged_entries, avg_drop_pct (mean of (avg_entry - add_price) /
   avg_entry for longs, mirrored for shorts, as a percent), flagged_net_pnl_inr,
   add_on_win_rate (share of flagged add-ons that were profitable)}.
7. name "Adding to a losing position"; formula_note = one plain paragraph a trader can
   read with the actual numbers filled in.

TESTS
Hand-built Trade lists with hand-computed expectations:
- fires on a constructed case: exact cost, ids, metrics
- add-on price equal to the average is NOT flagged; just below is
- add-on above the average (adding to a winner) is NOT flagged
- two existing lots: the weighted average is used, not a simple mean
- a partial exit before the add-on removes that quantity from the existing position
  (use exit_time strictly after entry_time)
- short direction mirrors the long logic
- add-on with no qualifying existing position is not evaluated
- multi-slice add-on aggregated as one event
- non-add-on entries are ignored
- fewer than 3 flagged -> None; net positive -> None
- determinism

DATASET TESTS (parse_orders -> pair_orders -> detect):
- clean.csv: None
- single_averaging_down.csv: fires. Map flagged entries to the ground-truth
  entry_order_ids (the add-on entry orders): assert precision >= 0.8 and recall >=
  0.6; assert cost within 0.5x to 2.0x of injected_loss_inr. Print precision, recall,
  cost, injected_loss_inr, and tell me exactly what injected_loss_inr measures for
  this habit and whether the generator forces the add-on legs to lose.
- mixed.csv and the other single_* datasets: do not assert. Print whether it fires on
  each, and list any flagged entries on datasets where it is not planted, with a
  one-line reason.

MULTI-SEED (in memory, via generate_dataset_in_memory): 30 clean months seeds
980-1009 -> assert at most 1 fires; 30 months with averaging_down planted at medium
seeds 1010-1039 -> assert detection >= 0.8. Print both. Confirm `make data`
reproduces byte-identical committed files.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 5e: averaging_down
detector" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, stage only relevant files, commit with
the message "feat(detectors): averaging_down", and push to origin main. Show me
`git status` and `git log --oneline -3` afterwards. Never commit .env, API keys, or
node_modules. If tests fail, do not commit; fix first.

Result: worked. AveragingDownDetector implemented in backend/app/detectors/averaging_down.py with fixed thresholds (MIN_FLAGGED=3, CONFIDENCE_DIVISOR=6). Single_averaging_down.csv: precision=1.000, recall=1.000, cost=₹6,879.95 vs injected=₹8,373.05 (ratio 0.822, within [0.5, 2.0]). Clean.csv, mixed.csv, and all other single_* datasets return None (0 false positives). Multi-seed: clean 0/30 fires, planted 30/30 detected (100%). make data byte-identical. 102 tests pass, ruff clean.

## Prompt 6: ranking and pipeline

Step 6: implement ranking in backend/app/ranking.py and add ONE new module,
backend/app/pipeline.py (this is the only tree addition). Tests go in
backend/tests/test_ranking.py (replace the skipped placeholder).

RULES: constants below are fixed. If an end-to-end test fails, STOP and report the
numbers and your diagnosis instead of adjusting a constant or loosening a test. In
your final summary state whether any detector file, threshold, generator file, or
committed dataset changed (expected: none).

DETECTOR REGISTRY
In app/detectors/__init__.py expose ALL_DETECTORS: the five detector instances in a
fixed order (holding_losers, revenge_trading, overtrading, oversizing,
averaging_down).

RANKING (ranking.py), named constants:
MIN_CONFIDENCE = 0.25, MIN_COST_INR = 500, MAX_HABITS = 3.
rank_habits(results: list[HabitResult], trades: list[Trade]) -> RankedResult
1. Drop results with confidence < MIN_CONFIDENCE or estimated_cost_inr < MIN_COST_INR.
   Record each dropped habit with the reason in `dropped`.
2. Sort by estimated_cost_inr descending; ties broken by key alphabetically.
3. Overlap handling (greedy, in sorted order): for each habit, overlap_share = (flagged
   trade ids already claimed by higher-ranked habits) / (its flagged trade ids).
   attributed_cost_inr = estimated_cost_inr * (1 - overlap_share), rounded to 2. Claim
   its ids. Document in the docstring that this is a proportional-by-count
   approximation, not an exact per-trade attribution. Record each overlap as
   {habits: [a, b], shared_trade_ids: [...]}.
4. Re-sort by attributed_cost_inr descending (same tie-break), keep the top MAX_HABITS.
5. RankedResult fields: habits (each: the HabitResult fields plus attributed_cost_inr
   and overlap_share), total_attributed_cost_inr (sum over the kept habits),
   overlaps, dropped, material (bool: True if at least one habit is kept), reason
   (when material is False, a plain sentence such as "No habit cleared the evidence
   bar this month"), and context {n_trades, gross_pnl_inr, gross_loss_inr, win_rate}.
   One habit is a valid result; do not require two.

PIPELINE (pipeline.py)
run_pipeline(source) -> PipelineResult: parse_orders -> pair_orders -> run every
detector in ALL_DETECTORS -> rank_habits. PipelineResult includes the IngestResult
warnings and counts, pairing anomalies, the RankedResult, and the full list of raw
detector outputs (needed by the evals). A detector raising an exception must NOT crash
the pipeline: catch it, log it, and record it in a `detector_errors` list. IngestError
propagates unchanged.

TESTS (test_ranking.py)
Unit tests with fabricated HabitResults:
- ordering by cost; tie-break by key; cap at 3; MIN_CONFIDENCE and MIN_COST_INR drops
  recorded with reasons
- overlap: two habits sharing half their ids -> exact attributed cost; fully
  overlapping lower habit -> attributed cost 0 and it is still reported; total is the
  sum of attributed costs
- zero habits -> material False with a reason; one habit -> material True
- determinism; detector exception is captured, not raised

END-TO-END (parse -> pair -> detect -> rank) on the committed datasets:
- clean.csv: material is False.
- Each single_* dataset: the planted habit is rank 1 and is the ONLY habit kept.
- mixed.csv: the kept habits are exactly the planted set. Print ranks, costs,
  attributed costs, confidences, and overlaps.
- messy.csv: pipeline completes, warnings present, no detector_errors.
- Print the confidence of every planted habit on every dataset. If a planted habit is
  dropped by MIN_CONFIDENCE or MIN_COST_INR, STOP and report instead of changing the
  constants.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 6: ranking and pipeline"
with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, stage only relevant files, commit with
the message "feat(ranking): top-3 selection, overlap handling, pipeline", and push to
origin main. Show me `git status` and `git log --oneline -3` afterwards. Never commit
.env, API keys, or node_modules. If tests fail, do not commit; fix first.
The mixed.csv printout: ranks, estimated cost, attributed cost, confidence, and overlaps.
The confidence of every planted habit on every dataset.
The integrity statement, with no detector file, threshold, or dataset changed.
The git log.

If any planted habit is dropped by the confidence or cost bar, Antigravity should stop and report it rather than adjust a constant. If it does, paste the numbers and we’ll decide together.

Result: stopped and reported per instructions. Holding_losers confidence fell below MIN_CONFIDENCE (0.25) on single_holding_losers.csv (0.09), mixed.csv (0.24), and messy.csv (0.15) because the disparity factor used the median hold of all losers instead of flagged outlier losers.

## Prompt 6b: holding_losers confidence fix

### Stop and Report: Planted Habit Dropped by `MIN_CONFIDENCE`

As required by the Step 6 rules:
> *"Print the confidence of every planted habit on every dataset. If a planted habit is dropped by MIN_CONFIDENCE or MIN_COST_INR, STOP and report instead of changing the constants. If any planted habit is dropped by the confidence or cost bar, Antigravity should stop and report it rather than adjust a constant. If it does, paste the numbers and we’ll decide together."*

`holding_losers` was detected by its detector with significant estimated rupee cost on all datasets where it is planted, but its computed **`confidence` falls below `MIN_CONFIDENCE = 0.25`** on `single_holding_losers.csv` (0.09), `mixed.csv` (0.24), and `messy.csv` (0.15). Consequently, `rank_habits` drops it during Step 1 filtering.

---

### 1. Confidence of Every Planted Habit on Every Dataset

| Dataset | Planted Habit | Intensity | Estimated Cost | Confidence | Threshold (`>= 0.25`) | Status in Ranking |
|---|---|---|---|---|---|---|
| `clean.csv` | *(None)* | — | — | — | — | **`material = False`** ✅ |
| `single_holding_losers.csv` | **`holding_losers`** | **medium** | **₹56,518.88** | **0.09** | **0.09 < 0.25** | ❌ **DROPPED** (`material = False`) |
| `single_revenge_trading.csv` | **`revenge_trading`** | **medium** | **₹87,898.20** | **1.00** | 1.00 ≥ 0.25 | ✅ **KEPT (Rank 1)** |
| `single_overtrading.csv` | **`overtrading`** | **medium** | **₹34,666.50** | **0.75** | 0.75 ≥ 0.25 | ✅ **KEPT (Rank 1)** |
| `single_oversizing.csv` | **`oversizing`** | **medium** | **₹130,727.40** | **1.00** | 1.00 ≥ 0.25 | ✅ **KEPT (Rank 1)** |
| `single_averaging_down.csv` | **`averaging_down`** | **medium** | **₹6,879.95** | **1.00** | 1.00 ≥ 0.25 | ✅ **KEPT (Rank 1)** |
| `mixed.csv` | **`holding_losers`** | **high** | **₹97,841.20** | **0.24** | **0.24 < 0.25** | ❌ **DROPPED** |
| | **`revenge_trading`** | **medium** | **₹48,177.00** | **1.00** | 1.00 ≥ 0.25 | ✅ **KEPT (Rank 1)** |
| | **`overtrading`** | **low** | **₹22,629.00** | **0.50** | 0.50 ≥ 0.25 | ✅ **KEPT (Rank 2)** |
| `messy.csv` | **`holding_losers`** | **high** | **₹84,499.65** | **0.15** | **0.15 < 0.25** | ❌ **DROPPED** |
| | **`revenge_trading`** | **medium** | **₹58,032.45** | **1.00** | 1.00 ≥ 0.25 | ✅ **KEPT (Rank 1)** |
| | **`overtrading`** | **low** | **₹31,281.75** | **0.50** | 0.50 ≥ 0.25 | ✅ **KEPT (Rank 2)** |

*(Note: `messy.csv` completes through `run_pipeline` with 9 warnings and 0 detector errors).*

---

### 2. Diagnosis: Why is `holding_losers` Confidence Below 0.25?

In [backend/app/detectors/holding_losers.py](file:///Users/mohammadadnankhan/Desktop/trademirror/backend/app/detectors/holding_losers.py#L90-L95), confidence is computed per the Step 5a formula:
$$\text{confidence} = \min\left(1, \frac{\text{flagged}}{10}\right) \times \min\left(1, \max\left(0, \frac{\frac{\text{median\_loser\_hold}}{\text{median\_winner\_hold}} - 1.0}{2.0}\right)\right)$$

For $\text{confidence} \ge 0.25$ (when sample saturation is 1.0), the formula mathematically requires:
$$\frac{\text{median\_loser\_hold}}{\text{median\_winner\_hold}} \ge 1.50$$

However, in [data/generator.py](file:///Users/mohammadadnankhan/Desktop/trademirror/data/generator.py#L400-L420), holding duration is only planted on a **subset** of losers:
- **Medium intensity** (`single_holding_losers.csv`): only **35%** of losing trades have prolonged hold times. The median (50th percentile) is dominated by the remaining 65% normal losers.
  - Winner median hold: **21.5 min**
  - Loser median hold: **25.5 min**
  - Hold ratio: $\frac{25.5}{21.5} = \mathbf{1.19}$
  - Confidence: $1.0 \times \frac{1.19 - 1.0}{2.0} = \mathbf{0.09}$
- **High intensity** (`mixed.csv`): **60%** of losing trades are prolonged, but because 40% are unaffected:
  - Winner median hold: **21.0 min**
  - Loser median hold: **31.0 min**
  - Hold ratio: $\frac{31.0}{21.0} = \mathbf{1.48}$ (just shy of 1.50)
  - Confidence: $1.0 \times \frac{1.48 - 1.0}{2.0} = \mathbf{0.24}$ (0.01 below 0.25)
- **High intensity** (`messy.csv`):
  - Winner median hold: **23.0 min**, Loser median hold: **30.0 min**
  - Hold ratio: $\mathbf{1.30}$
  - Confidence: $1.0 \times \frac{1.30 - 1.0}{2.0} = \mathbf{0.15}$

---

### 3. Printout on `mixed.csv`

#### Current behavior (with `MIN_CONFIDENCE = 0.25` strictly enforced):
- **Kept habits (2)**:
  1. `revenge_trading`: estimated cost **₹48,177.00**, attributed cost **₹48,177.00**, confidence **1.00**, overlap **0.0%**
  2. `overtrading`: estimated cost **₹22,629.00**, attributed cost **₹22,629.00**, confidence **0.50**, overlap **0.0%**
- **Dropped habits (1)**:
  - `holding_losers`: estimated cost **₹97,841.20**, confidence **0.24** (reason: `confidence 0.24 < 0.25`)
- **Total Attributed Cost**: **₹70,806.00**
- **Overlaps**: `[]`

#### If `holding_losers` is retained (clears the confidence bar):
- **Kept habits (3)**:
  1. `holding_losers`: estimated cost **₹97,841.20**, attributed cost **₹97,841.20**, confidence **0.24**, overlap **0.0%**
  2. `revenge_trading`: estimated cost **₹48,177.00**, attributed cost **₹28,103.25**, confidence **1.00**, overlap **41.67%** (shares 5 of 12 trades with `holding_losers`)
  3. `overtrading`: estimated cost **₹22,629.00**, attributed cost **₹22,629.00**, confidence **0.50**, overlap **0.0%**
- **Total Attributed Cost**: **₹148,573.45**
- **Overlaps**: `[{'habits': ['holding_losers', 'revenge_trading'], 'shared_trade_ids': ['P0010', 'P0014', 'P0064', 'P0074', 'P0078']}]`

---

### 4. Integrity Statement

- **Thresholds modified**: **None** (`MIN_CONFIDENCE = 0.25`, `MIN_COST_INR = 500`, `MAX_HABITS = 3` are strictly implemented as given).
- **Existing detector files modified**: **None**.
- **Generator file modified**: **None**.
- **Committed datasets modified**: **None**.

---

### Decision Options for Moving Forward

Please let me know how you would like to proceed:

1. **Option A (Update `holding_losers.py` confidence formula)**: Change the disparity factor denominator or baseline so that a ratio of 1.15–1.20 yields confidence $\ge 0.25$ (e.g. based on flagged ratio or adjusting the disparity denominator).
2. **Option B (Adjust `MIN_CONFIDENCE` in `ranking.py`)**: Lower `MIN_CONFIDENCE` (e.g. to `0.08` or similar).
3. **Option C (Update `generator.py` hold duration planting)**: Increase hold durations or planting ratios for holding losers in `generator.py` so the median loser hold time shifts $\ge 1.5\times$ winner hold time, and regenerate `data/`.

DECISION on your Step 6 report: Option A. Do NOT change MIN_CONFIDENCE,
MIN_COST_INR, MAX_HABITS, any other detector, or the generator.

Rationale: the confidence formula used the median hold of ALL losers, which is the
wrong statistic when only a subset of losers is affected. Fix the formula on
principle; do not fit it to the datasets.

PART A: holding_losers confidence only (backend/app/detectors/holding_losers.py)
Detection logic, thresholds, flagged ids, and estimated cost must stay byte-for-byte
unchanged. Only the confidence value changes.
New confidence = min(1, flagged_count / 10) *
                 min(1, max(0, (flagged_median_hold / median_winner_hold - 1) / 2))
where flagged_median_hold is the median hold_minutes of the FLAGGED losers.
- Add flagged_median_hold_min and flagged_hold_ratio to metrics. Keep the existing
  hold_ratio metric (all losers) for transparency.
- Update the docstring and formula_note wording to explain confidence plainly.
- Edit existing tests ONLY where they assert the old confidence value; recompute the
  expected value by hand and list each edited assertion in your summary.
- Add tests: (a) confidence is higher when flagged losers are held longer, other
  inputs equal; (b) exactly 3 flagged with a flagged ratio of 2.0 gives
  0.3 * 0.5 = 0.15; (c) 10+ flagged with a ratio of 3.0 or more gives 1.0;
  (d) the detector still returns None in every case it did before.

PART B: regression proof (print before/after)
For every committed dataset, print the holding_losers result before and after your
change: fires or not, flagged ids, estimated cost, confidence. Assert that fires,
flagged ids, and cost are IDENTICAL; only confidence may differ. Re-run the multi-seed
holding_losers checks with the same seeds as in Step 5a and the lots-fix step; the
clean fire count and the planted detection count must be exactly what they were.

PART C: finish Step 6 as originally specified
Re-run the Step 6 end-to-end tests with no other change. Expected: clean.csv
material False; each single_* has its planted habit as rank 1 and the only habit
kept; mixed.csv keeps exactly holding_losers, revenge_trading, and overtrading.
Print the new confidence of every planted habit on every dataset, and for mixed.csv
print ranks, estimated cost, attributed cost, confidence, and overlaps. If ANY planted
habit is still dropped, STOP and report again.

PROMPTS.md: log your Step 6 stop-and-report and this decision message verbatim as
"## Prompt 6b: holding_losers confidence fix" with a Result line. Do not tidy my
wording.

GIT: two commits, pushed to origin main, only when `make test` and `ruff check .`
pass:
1. "fix(detectors): holding_losers confidence uses flagged-trade hold ratio"
   (Part A and its tests)
2. "feat(ranking): top-3 selection, overlap handling, pipeline"
Show me `git status` and `git log --oneline -4` afterwards. Never commit .env, API
keys, or node_modules. In your final summary, state explicitly: every threshold,
detector file, generator file, dataset, and existing test changed (expected: only
holding_losers.py, its confidence assertions, and the new Step 6 files).
What to check in the reply
Part B’s before/after table. Fires, flagged ids, and cost must be identical on every dataset, with only the confidence column changing. If any of the other three differ, the fix changed detection, which it must not do.
Multi-seed counts. They should match the earlier runs exactly. The confidence score doesn’t affect whether the detector fires, so any change means something else moved.
mixed.csv. All three planted habits should be kept. Expect holding_losers first, then revenge_trading with an attributed cost lower than its raw estimate (earlier numbers: 41.67% overlap, about ₹28,103 attributed). That is the proportional-attribution rule working.
The confidence table. A planted habit that’s still dropped means we’ve got a second problem, and Antigravity should stop again.

Result: worked. Holding_losers confidence updated to use flagged loser hold ratio, leaving detection logic, thresholds, flagged IDs, and costs 100% byte-for-byte identical while lifting confidence on planted datasets (single_holding_losers: 1.00, mixed: 0.83, messy: 1.00). All single_* datasets isolate their planted habit at Rank 1. Mixed.csv retains holding_losers (Rank 1, ₹97,841.20), revenge_trading (Rank 2, ₹28,103.25 attributed with 41.67% overlap), and overtrading (Rank 3, ₹22,629.00). Clean.csv material=False. 122 tests pass, ruff clean.

## Prompt 7: narrative layer and verifier

Step 7: implement the narrative layer and the verifier. This is one step because the
verifier is what makes the narrative safe to show.

TREE ADDITION: exactly one new module, backend/app/narrative.py (the orchestrator).
Everything else goes in files that already exist: app/llm/client.py, app/llm/
templates.py, app/verifier.py, prompts/narrative_system.md, app/config.py,
.env.example, and tests in backend/tests/test_verifier.py and
backend/tests/test_llm.py (replace the skipped placeholders).

RULES: do not touch detectors, ranking thresholds, the generator, or committed
datasets. Tests must never make real network calls: add an autouse fixture in
conftest.py that makes any real httpx request raise, and mock the transport in the
LLM tests. If anything unexpected comes up, STOP and report instead of working around
it. In your final summary list every file changed outside the files named above
(expected: none).

PRINCIPLE: all numbers come from deterministic code. The LLM only explains numbers it
is given. It never sees raw orders, only the facts bundle below.

1) FACTS BUNDLE (narrative.py): build_facts(ranked: RankedResult, trades: list[Trade])
-> Facts. Deterministic and JSON-serialisable. Contains:
- context: n_trades, gross_pnl_inr, gross_loss_inr, win_rate, total_attributed_cost_inr
- per kept habit (same order as ranked.habits): key, name, attributed_cost_inr,
  estimated_cost_inr, overlap_share, confidence, metrics, formula_note,
  approved_rule (a fixed rule string per habit from templates.py; see 2), and up to 3
  example trades chosen deterministically (largest loss first, ties by trade_id), each
  with trade_id, trading_date, symbol, instrument_type, strike, direction,
  hold_minutes, quantity, gross_pnl
- allowed_numbers: every number appearing anywhere in the bundle, plus every number in
  each approved_rule
- allowed_trade_ids: the flagged trade ids of the kept habits
- allowed_dates: every ISO date appearing in the bundle
Only kept habits appear. Raw orders, order ids, and file contents are never included.

2) TEMPLATES (templates.py): per habit key, a deterministic fallback:
{explanation (2 sentences max, numbers filled in from metrics and attributed cost),
rule (one concrete behavioural rule; fixed text per habit; any numbers in it are its
own fixed constants, for example "wait 30 minutes after a loss before the next entry")}.
Plus a deterministic summary sentence and a deterministic "nothing material" message.
Templates describe behaviour only. No advice on what to buy or sell, no predictions.

3) VERIFIER (verifier.py): verify_narrative(narrative, facts) -> VerificationReport with
passed (bool), checked_numbers, checked_trade_ids, and failures (list of {field, kind,
value, message}). Checks:
a) Numbers. Tokenise all text in the narrative. First remove trade ids (pattern
   P\d{4}) and ISO dates, and check those against allowed_trade_ids and allowed_dates
   separately. Then extract every remaining numeric token. Handle: rupee amounts with
   a rupee sign, Indian grouping (1,48,573) and western grouping (148,573), decimals,
   percentages, multiples like 2.1x, and the words/suffixes "lakh" and "k" (convert to
   numbers). A number passes if some allowed number matches within max(1, 1% of the
   allowed value). Percentages may match an allowed share expressed as a fraction
   (0.4167 vs 41.7%) within 0.5 percentage points. A number that matches nothing is a
   failure, EXCEPT ordinals and the counts 1 to 3 used as small quantifiers only if
   they also appear in allowed_numbers; otherwise they are checked like everything
   else. Document the limitation that numbers written as words are not checked and
   instruct the LLM (prompt file) to always use digits.
b) Trade ids and dates: every id and date mentioned must be in the allowed sets.
c) Structure: the narrative's habit keys must equal exactly the kept habit keys, in the
   same order; no extra or missing habits.
d) Forbidden content: case-insensitive blocklist for recommendations and predictions,
   for example buy/sell/hold instructions, "will rise/fall/go up/go down", "guaranteed",
   "you should trade", "price target". Keep the blocklist as a named constant and test
   it.
e) The rule field of each habit may contain numbers only from allowed_numbers (which
   includes that habit's approved_rule numbers).
Return ALL failures, not just the first.

4) LLM CLIENT (client.py): a single function call_llm(system, user, settings) -> str
using httpx with a timeout, provider chosen by settings.LLM_PROVIDER ("gemini",
"anthropic", or "none"), model from LLM_MODEL, key from LLM_API_KEY. Do not hard-code
or guess model names; they come from the environment. Read the provider's current REST
documentation in your tools if needed. No key or provider "none" means: never make an
HTTP call. Add LLM_PROVIDER (default "none") and LLM_TIMEOUT_SECONDS (default 20) to
config.py and .env.example. Never log the key or the full prompt.

5) ORCHESTRATOR (narrative.py): generate_narrative(ranked, trades, settings) ->
NarrativeResult {narrative, source ("llm" | "template"), fallback_reason (None or short
text), verification (VerificationReport), llm_attempts (int)}.
Flow:
- not ranked.material -> deterministic "nothing material" narrative, source "template",
  no LLM call.
- no key or provider none -> template narrative, source "template", reason "no_llm_key".
- otherwise attempt 1: call the LLM with the system prompt and the facts as JSON ->
  parse JSON (strip code fences) -> pydantic schema validation -> verify_narrative. If
  it passes, source "llm".
- if parsing, schema, or verification fails, attempt 2 ONCE, adding the failure list
  to the user message. If that also fails, or any HTTP error or timeout occurs, use the
  template narrative with a fallback_reason naming the cause. Never more than 2 LLM
  calls. Never raise to the caller because of an LLM problem.
- the template narrative is also passed through verify_narrative; if the template ever
  fails verification, raise an internal error (that is a bug, and tests must prevent it).
Narrative schema: {summary: str, habits: [{key, explanation, rule}]} with the field
lengths capped (summary 300 chars, explanation 400, rule 250).

6) SYSTEM PROMPT (prompts/narrative_system.md): written for the model. It must say: you
are explaining a trader's own computed statistics; use ONLY facts in the JSON; every
number must be written with digits, copied from the facts (rounded to the nearest
rupee is fine); cite at most one trade id per habit; keep each explanation to two
sentences in plain English for a retail trader; write each rule by restating the
approved_rule in your own words without changing any number; never give advice about
what to buy or sell, never predict markets, never mention anything not in the JSON;
output strict JSON matching the schema with no preamble and no code fences.

7) TESTS
Verifier (test_verifier.py): passes a correct narrative; rejects a number not in facts
(for example a made-up rupee total); rejects an unknown trade id; rejects an unknown
date; tolerance: accepts "about ₹98,000" for 97,841.20 and rejects 5% off; Indian and
western grouping both parse; "1.5 lakh" and "98k" convert; percentage versus fraction;
approved_rule numbers allowed in the rule only; extra or missing habit keys fail; order
mismatch fails; forbidden phrases fail (one test per phrase family); all failures
returned together; a hallucinated narrative claiming a loss of ₹2,00,000 is rejected.
LLM and orchestrator (test_llm.py, transport mocked): no key makes zero HTTP calls and
returns the template; a good mocked LLM response gives source "llm"; invalid JSON then
a good second response gives source "llm" with llm_attempts 2; invalid twice falls back
with a reason; verification failure triggers exactly one retry and the retry message
contains the failures; HTTP 500 and a timeout fall back without raising; never more than
2 calls; zero habits makes no LLM call.
Self-consistency (parametrised over ALL committed datasets, through parse -> pair ->
detect -> rank -> build_facts): the template narrative passes verify_narrative on every
dataset where material is True, and the facts bundle for clean.csv yields the
"nothing material" message. Also assert determinism: the same input gives byte-identical
facts JSON.

8) PLAUSIBILITY CHECK (print only, no code change): for every committed dataset print
n_trades, gross_pnl_inr, gross_loss_inr, total_attributed_cost_inr, and the ratio
total_attributed_cost_inr / gross_loss_inr. If any ratio exceeds 1.0, STOP and report;
do not change ranking or any detector.

9) MANUAL SMOKE (not a test): add `python -m app.narrative <path-to-csv>` that runs the
full pipeline and prints the facts, the narrative, the source, the fallback_reason, and
the verification report. Run it on mixed.csv with no key and show me the output.

Update PROMPTS.md: append this prompt verbatim as "## Prompt 7: narrative layer and
verifier" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, stage only relevant files, commit with
the message "feat(narrative): grounded explanations with verifier and template
fallback", and push to origin main. Show me `git status` and `git log --oneline -3`
afterwards. Never commit .env, API keys, or node_modules. If tests fail, do not
commit; fix first.

Result: worked. Orchestrator implemented in backend/app/narrative.py with build_facts and generate_narrative. Grounding verifier in backend/app/verifier.py checks numbers (Indian/western grouping, lakh/k suffixes, percentages, multiples, ordinals), trade IDs, dates, structure, and forbidden phrases. Deterministic templates in backend/app/llm/templates.py with fixed approved rules. Unified client in backend/app/llm/client.py. All 153 tests pass with network-blocking autouse fixture in conftest.py. Template self-consistency proved on all 8 committed datasets. Plausibility check: all ratios <= 1.0 (max 0.5933 on mixed.csv). Manual smoke runs and verifies cleanly.

## Prompt 7b: wording and rule fixes

Step 7b: small corrections to the narrative layer. Do not touch detectors, ranking,
the generator, committed datasets, or verifier logic other than the blocklist below.
If anything unexpected comes up, STOP and report. In your final summary list every
file changed (expected: templates.py, verifier.py, tests, PROMPTS.md only).

A) Remove unsupported claims from templates.
The holding_losers template says "in excess decay". Remove it. Templates may only
state what the detector computed. Reword each cost phrase to say what it measures:
- holding_losers: "extra loss beyond what you normally lose on a losing trade"
- revenge_trading: "net loss on these re-entries"
- overtrading: "net loss on the extra trades"
- oversizing: "extra loss attributable to the larger size"
- averaging_down: "net loss on the added positions"
The summary sentence should say "combined attributed cost" once and the habit
sentences should carry the precise definition. Keep every number grounded as before.

B) Tighten the verifier blocklist.
Add a second named constant UNSUPPORTED_CLAIM_TERMS (case-insensitive, whole-word
matching): decay, theta, vega, volatility, implied volatility, IV, premium erosion,
time value, sentiment, news, earnings, expiry effect. A narrative containing any of
them fails with kind "unsupported_claim". Add one test per term family and one test that
all five templates pass cleanly.

C) Derive rule numbers from the trader's own data.
- holding_losers rule: the time stop equals the trader's median winner hold, rounded
  to the nearest 5 minutes, minimum 5. Example text: "Exit any losing trade that has
  not recovered within N minutes of entry, which is about how long your winning trades
  last."
- overtrading rule: the daily cap equals ceil(median_daily_trades) + 1. Tell me whether
  this was already derived or hard-coded.
- revenge_trading, oversizing, averaging_down: tell me for each whether its rule
  contains a number and where that number comes from. Keep fixed constants only where
  the number is a rule of thumb rather than a property of the trader (for example a
  30-minute cooldown), and say so in a template comment.
Every derived number must appear in the facts bundle's allowed_numbers and in the
habit's approved_rule so the verifier accepts it. Add tests: two different traders
(median winner hold 12 vs 90 minutes) get different time stops; the derived rule
passes the verifier; changing median_daily changes the cap.

D) Re-run and print
- the full test suite (the self-consistency test over all datasets must still pass)
- `python -m app.narrative data/datasets/mixed.csv` and
  `python -m app.narrative data/datasets/single_overtrading.csv`, full output

Update PROMPTS.md: append this prompt verbatim as "## Prompt 7b: wording and rule
fixes" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, commit "fix(narrative): remove
unsupported claims, derive rules from trader data" and push to origin main. Show me
`git status` and `git log --oneline -3`. Never commit .env, API keys, or node_modules.

Result: worked. Templates updated with exact detector cost descriptions removing "in excess decay". UNSUPPORTED_CLAIM_TERMS added to verifier with whole-word regex matching. Dynamic derived rules implemented: holding_losers time stop derives from median winner hold (nearest 5m, min 5) and overtrading cap derives from ceil(median_daily_trades) + 1. All derived numbers included in facts allowed_numbers. All 157 tests pass, including new verifier unit tests and full-dataset self-consistency. Manual smoke runs cleanly on mixed.csv and single_overtrading.csv.

## Prompt 7c: summary grammar and oversizing rule

Step 7c: two small corrections. Do not touch detectors, ranking, the generator,
committed datasets, or verifier logic. If anything unexpected comes up, STOP and
report. In your final summary list every file changed (expected: templates.py, tests,
PROMPTS.md only, plus narrative.py only if build_facts needs the median_lots value).

A) Summary sentence grammar (templates.py)
- With exactly one habit: "1 habit stood out this month: <habit name in lowercase
  first letter, as a noun phrase>, with an attributed cost of ₹X." Make sure all five
  habit names read naturally in this sentence; if any name does not, add a short
  lowercase "label" field per habit in templates.py and use it here and nowhere else.
- With 2 or 3 habits: keep the current sentence.
- All numbers still come from the facts bundle and must pass the verifier.

B) Oversizing rule derived from the trader's own size
Replace "maximum of 2 lots" with: "After two wins or two losses in a row, keep your
position at your usual N lot(s) instead of increasing it." where N =
max(1, round(median_lots)) from the oversizing metrics. Singular "lot" when N is 1,
plural otherwise. N must appear in the habit's approved_rule so the verifier accepts it.
Update the template comment: the number is now derived from the trader's data.
Tests: a trader with median_lots 1 and one with median_lots 5 get different rules, both
pass the verifier; singular/plural wording is correct; the five templates still pass
the verifier on all datasets (self-consistency test unchanged).

C) Print
- the full test suite result and `ruff check .`
- `python -m app.narrative` on single_overtrading.csv, single_oversizing.csv, and
  mixed.csv (summary and habit rules only is fine)

Update PROMPTS.md: append this prompt verbatim as "## Prompt 7c: summary grammar and
oversizing rule" with a "Result:" line. Do not tidy my wording.

GIT: when `make test` and `ruff check .` pass, commit "fix(narrative): readable
single-habit summary, size rule derived from trader's median lots" and push to origin
main. Show me `git status` and `git log --oneline -3`. Never commit .env, API keys, or
node_modules.

Result: worked. Single-habit summary sentence format updated with HABIT_LABELS lowercase noun phrases in templates.py. Oversizing approved rule dynamically derives N = max(1, round(median_lots)) with singular/plural lot(s) wording, included in approved_rule and verified. All 159 tests pass, ruff clean, and verified smoke outputs confirmed on single_overtrading, single_oversizing, and mixed datasets.
