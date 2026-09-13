# Full v3-to-v4 migration plan

**Planning baseline:** 12 September 2026. This plan is for the current v4
architecture and the v3 behavior recorded in
[the archived current state](../archive/v3/Current%20state.md), the archived API
and strategy guides, and the v3 source in Git `HEAD`. The existing
[initial implementation plan](../archive/v4/Initial%20implementation%20plan.md)
is retained as design history. This document authorizes no production data
cutover or live broker order by itself.

## Outcome and operating choices

Build a complete local stock-screening, portfolio and backtesting app on the
modular backend. Keep the frontend limited to readable tables, forms, status,
and simple charts. Preserve each useful v3 workflow, but use the v4 catalog,
immutable research inputs, ledger, and versioned decisions as authorities.
Implement API/use-case parity rather than reproducing mutable v3 tables or all
v1 URLs. A temporary read-only v1 compatibility layer is acceptable only if a
specific consumer still needs it; record that consumer and an end date.
The deployment assumption for this migration is a local, single-operator app;
a public or multi-user hosted service needs a separate identity, tenancy and
market-data licensing design.

Keep one local SQLite `system.db` for transactional catalog, job, and ledger
metadata and immutable artifacts for market/research/backtest evidence. Use
the existing package boundaries. Do not add distributed services, a frontend
framework, or a second authoritative portfolio store to finish migration.
Package metadata still says `3.0.0` although the architecture is called v4;
set a release version only after the parity and migration gates pass.

## Capability inventory and replacement contract

| v3 capability | Current v4 seam | Required replacement behavior |
|---|---|---|
| Day 0 NSE/BSE import and Kite instrument sync | `reference_data`, `application.providers` | Import and validate exchange files, match by ISIN and exchange/series, retain symbol/token history, publish as-of universe and exclusion reasons. |
| Market-data refresh and historical backfill | `market_data`, `application.ingestion` | Scheduled/triggered Kite plus exchange EOD ingestion, bounded retries, completeness checks, immutable raw and normalized snapshots, resumable backfill. |
| Corporate-action detection and history repair | Reference contracts and catalog invalidation | Record source action and effective/known dates; version adjusted bars, invalidate dependent research, never cascade-delete history. |
| Strategy 1 and Strategy 2 indicators | `indicators` | Rebuild every enabled v3 factor with declared lookback, inputs, adjustment basis, missing-value policy and golden fixtures. |
| Daily percentiles/scores and weekly rankings | `strategies` snapshots | Publish feature → percentile → score → weekly ranking lineage; preserve tie, eligibility, penalty, and week-boundary rules or document intentional differences. |
| Configuration and strategy selection | Revision contracts | Validated draft/approved revisions, optimistic updates, effective dates and audit history; no silent mutation of old run definitions. |
| Generate, approve, reject and process actions | `portfolio_engine`, `execution_gateway` | Persist decision/order lifecycle, approvals and paper fills with idempotency and a single accounting projection. No close signal may fill at an earlier open. |
| Manual buy/sell, capital events and FIFO journal | `portfolio_accounting`, ledger | Record external cash, manual fills, fees/taxes, corrections and provenance; rebuild holdings, cash, realised P&L and journal from events. |
| Holding summaries, price sync and live quotes | Ledger projections, market-data quote port | As-of valuations and summary history; explicit freshness/market-state labels for live quotes, never use a quote as a confirmed fill. |
| Backtest modes, reports and history | `backtesting`, catalog | Next-tradable-bar simulation, stops, costs/taxes, cash flows, reproducible input manifests, separate results and history queries. |
| Pipeline orchestration and progress stream | Durable jobs | Typed jobs for each stage and full pipeline, lease/cancel context, retries, resume points and cursor events. |
| Dashboard, action/portfolio/backtest pages | Flask templates plus small JS | Minimal navigation and forms/tables for the above workflows, loading/error states, charts only where needed to inspect results. |
| Broker connectivity | Read-only Kite adapters and paper broker | Quote/instrument/data access first; live order submission remains gated on reconciliation, dry-run and explicit release review. |

The current implementation has only `system.echo` and `artifacts.recover`
registered as jobs. Existing class contracts do not establish end-to-end
workflow parity. Treat all rows above as delivery work until verified through
the new API and minimal UI.

Across every slice, enforce four invariants: (1) a historical decision sees
only inputs known by its cutoff, (2) money and quantities use explicit units,
precision and rounding rules, (3) retries cannot duplicate a published
artifact, command or fill, and (4) missing, stale or disputed data is visible
as a status rather than silently replaced. A run manifest must record policy,
formula, provider, input hashes, code revision and clock/calendar basis.

## Data-source decision: remove yfinance from the required path

The v3 code uses yfinance in two places. `InitService` calls `Ticker.info` for
`marketCap`, `regularMarketPrice`, industry/sector, share-count/float/ownership
fields and all-time high/low; it filters the initial universe at ₹500 crore
market cap and ₹75 price. Searches of the v3 services show the other fields
being stored but not used in the active factor, action or sizing calculations.
Strategy 2's benchmark adapter first asks Kite for Nifty 500 candles and uses
`^CNX500` through yfinance only if Kite is unavailable. The current v4
`YFinanceHistoricalBarsProvider` has tests but is not wired into a job.

**Decision:** use Kite historical index candles as the benchmark source,
including Nifty 500 for Strategy 2. Discover and record each index token from
dated Kite instrument snapshots, and verify actual date coverage for each
index a strategy needs. Kite supports historical index candles, but an index
being present in the instrument list does not guarantee complete history
([Kite index-history guidance](https://kite.trade/forum/discussion/3084/index-data-in-historical-api),
[reported gaps](https://kite.trade/forum/discussion/5166/missing-index-data)). If
required dates are missing, qualify or block that run; do not silently splice
in Yahoo data. Remove yfinance from the required dependency after the Kite
index and equity fixtures pass. Preserve legacy Yahoo market-cap values only
as labelled migration evidence, not as new facts.

Use a point-in-time **turnover/liquidity screen as the primary new universe
policy**. This matches the app's immediate purpose: avoiding stocks that
cannot absorb the intended order, regardless of company size. Keep a separate
`legacy_mcap_500` replay mode for imported v3 runs, using only market-cap
snapshots actually recorded at the time; do not backfill historical size from
today's data. The new policy needs a named strategy revision and a v3-versus-v4
membership/backtest comparison before release, but no new yfinance request.
For the turnover policy:

1. Import eligible equity securities by ISIN, exchange and series; reject
   funds/ETFs and disallowed or suspended series using explicit rules.
2. After each completed exchange session, use official exchange **total
   traded value** where licensed/available. If unavailable, label
   `close × traded volume` as an approximation. Do not combine the two bases
   without recording source and basis per observation.
3. Compute a versioned 60-session **median** daily traded value with at least
   54 valid sessions of coverage. Evaluate date *T* using only data published
   by the prior cutoff. Preserve v3's ₹75 price gate using a completed
   Kite/exchange close for its initial-universe comparison, and its separate
   ₹0.5 crore/day hard ranking exclusion for
   strategy parity; neither is automatically the new 60-session universe
   threshold. Calibrate that threshold on historical fixtures. Keep all
   thresholds configurable and record exact exclusion reasons. Short-history
   IPOs need a separately named policy, disabled by default.
4. Cap proposed order notional as a configurable fraction of recent traded
   value and handle zero volume, missing sessions, halts, auction-only days,
   splits, bonuses, exchange migration and duplicate NSE/BSE listings.

Turnover is a better first screen for **tradability** than market cap: a large
but thinly traded company can still be hard to enter or exit, while a smaller
actively traded one need not be illiquid. It does not measure company size or
guarantee executable depth; compare membership, sector/size exposure and
backtest outputs when replacing v3's ₹500 crore rule. If a separate size or
free-float rule is ever required, source and version those data from
exchange/company disclosures. Also rename/review v3's
`scaled_turnover`: its formula `(close × volume) / (close × 20-day mean volume)`
simplifies to `volume / 20-day mean volume`; it is relative volume, not traded
value divided by float or market cap. Do not port its name or claimed economic
meaning unchanged.

This recommendation follows the source contracts: [Kite daily candles](https://kite.trade/docs/connect/v3/historical/)
contain OHLC and volume, while the [NSE EOD reports](https://www.nseindia.com/all-reports)
publish a CM-UDiFF bhavcopy and [NSE's market-data format](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Snapshot_MDR_RT_CM_v1.19_1.pdf)
describes total traded value. [Nifty 500 methodology](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-500)
uses both market capitalisation and turnover, so one is not identical to the
other. [yfinance's own README](https://github.com/ranaroussi/yfinance/blob/main/README.md)
describes it as unaffiliated with Yahoo and advises checking data-use terms.
Validate exchange access and redistribution terms before embedding any feed
in a distributable app.

### Simple circuit-like candle filter

For the latest completed **equity** session, exclude new entries if volume is
zero, the bar is missing, or `open = high = low = close`. Add one `flat_ohlc`
column so the UI explains the exclusion. This is a deliberately conservative
proxy for a circuit-like/no-range day, not a verified upper or lower circuit;
the rare positive-volume, single-price day is an accepted false positive.
Do not build historical price-band storage or separate upper/lower circuit
classifications for this migration. Apply the rule only to equities, not
non-tradable benchmark indices. Existing holdings remain in the portfolio;
the fill model must not execute on a zero-volume or missing bar.

If live order submission is considered later, check the then-current Kite
full quote and broker result immediately before/after the order. This is a
separate execution safeguard, not a reason to complicate the screening rule.
[Kite full-quote fields](https://kite.trade/docs/connect/v3/market-quotes/)
include current limits, but its
[historical candles do not include past limits](https://kite.trade/forum/discussion/9544/any-way-to-check-if-a-stock-has-hit-upper-lower-circuit-in-historical-data).

## Implementation sequence and acceptance gates

Each phase should be a reviewable PR with schema changes and fixtures where
appropriate. Complete the phase's gate before depending on it in the next
phase. Keep the existing dirty working tree intact; do not reset, restore or
delete user changes to recover v3 code. Read old source through Git history
and archive fixtures separately.

### 0. Baseline and migration harness

- Inventory v3 routes, tables, formulas, reports and UI actions against the
  matrix above; record owner, input, output and proposed v4 endpoint for each.
- When present, back up `market_data.db`, `personal.db`, `backtest.db`, relevant
  CSVs and reports with hashes. Build a **read-only** v3 importer that opens copies,
  detects schema versions and produces counts/checksums; no write to legacy DBs.
- Save a small anonymised fixture set: NSE/BSE duplicates, ticker/series
  changes, corporate actions, both strategies, actions, FIFO, capital events
  and one backtest. Record v3 outputs and intended correction deltas.
- Gate: repeated import is idempotent; source files are unchanged; every v3
  row maps to a target artifact, ledger event, explicit exclusion or a named
  unresolved category. Restore a copied database in CI.

### 1. Reference, liquidity and provider inputs

- Implement NSE/BSE and Kite instrument snapshots, ISIN/series/token matching
  with effective intervals, exchange calendars and a versioned universe
  policy. Never infer historical membership from today's instruments.
- Implement official traded-value ingestion or the labelled OHLCV proxy,
  availability timestamps, 60-session screen and exclusion audit. Add one
  Kite index-candle provider for Nifty 500 and every index actually referenced
  by a strategy; remove the Yahoo fallback from the required job registry.
- Gate: coverage for missing files, format drift, duplicate symbols, series
  changes, one-exchange-only stocks, IPO history, no trading, stale values and
  benchmark outage or partial index history. Test the ₹500 crore legacy replay
  against the new liquidity membership without using future data. Two runs
  from the same snapshots select identical members.

### 2. Market-data and corporate-action pipeline

- Add typed `reference.sync`, `market.ingest-eod`, `market.backfill` and
  `market.reconcile` handlers. Preserve request/response provenance and
  calendar/adjustment basis. Chunk and rate-limit fetches with bounded retry,
  timeout, cancellation and heartbeat; resume after a crash.
- Use corporate-action facts to publish new adjusted-bar revisions and
  catalog invalidation. Keep raw and old normalized snapshots for replay.
- Calculate the one `flat_ohlc` screen flag from completed equity bars and
  expose its exclusion reason alongside the zero-volume and missing-bar rules.
- Gate: partial provider response never appears COMPLETE; duplicate dates,
  OHLC violations, holiday gaps, revised history and split/bonus/rights events
  have deterministic quality statuses; restart does not duplicate artifacts.
  Fixtures cover zero volume, positive-volume flat OHLC and missing bars;
  index bars are not subjected to this equity-only screen.

### 3. Indicators and both strategies

- Port v3 indicator definitions and formula parameters into versioned,
  dependency-ordered calculations. Freeze outputs and formula/code revisions.
- Implement Strategy 1 and Strategy 2 factor/penalty configurations, daily
  percentiles/scores and weekly rankings. For Strategy 2, explicitly retain a
  versioned `quality=0` legacy-parity mode until real point-in-time fundamental
  inputs exist; never call the placeholder a measured quality factor.
- Gate: golden vectors cover EMA warm-up, RSI/PPO/ATR/Sortino, return skips,
  benchmark alignment, zero denominator, negative/NaN values, ties, missing
  factors, penalty order and week boundaries. Report every v3-v4 delta.

### 4. Portfolio ledger and paper/manual workflows

- Add account-opening/capital-in/capital-out, proposal, approval/rejection,
  submission, partial fill, fee/tax, cancellation, correction and
  reconciliation events. Version and hash commands. Derive holdings, cash,
  journal, realised/unrealised P&L and summaries solely from ledger replay.
- Make action generation use approved ranking + prior-close state; paper fills
  use the same engine/fill assumptions as backtests. Keep live submission off.
- Gate: oversells, insufficient cash, stale versions, duplicate/reused keys,
  broker timeout/unknown outcome, partial fills, split-adjusted holdings,
  out-of-order fills, fees and capital flows all have tested behavior. New
  entries after a zero-volume, missing or flat bar are rejected by policy;
  existing holdings remain, and no fill is fabricated on a zero-volume bar.

### 5. Backtests and reports

- Run both v3-style weekly and daily-stop modes through the pure engine on
  immutable as-of inputs. Model next tradable open, gaps, intraday stops,
  market holidays, missing bars, costs, taxes and cash events; preserve fill
  model and code provenance.
- Publish decisions, fills, equity, metrics and report as separately
  checksummed artifacts with one run manifest; expose paginated history and
  comparisons. Avoid deleting old runs when a correction occurs.
- Gate: no look-ahead; rerun is deterministic; equity reconciles to ledger
  projection at every step; benchmark gaps qualify results; restore/replay
  produces the same checksums. The simple flat-bar screen is reproducible and
  a zero-volume or missing bar never receives a simulated fill.

### 6. APIs and intentionally small frontend

- Expose versioned read/query APIs for universe, bars, features, rankings,
  actions, account, journal, backtests, reports and jobs; mutating APIs create
  commands/jobs with validated schemas, optimistic version and idempotency.
  Publish an OpenAPI contract and enforce pagination and bounded queries.
- Group the public `/api/v2` surface by `reference`, `market`, `research`,
  `actions`, `portfolio`, `backtests` and `operations`. Use stable IDs and
  explicit `as_of`/revision parameters on historical reads. Return a
  consistent error envelope with retryability, correlation ID and field-level
  validation errors; return `409` for stale versions or reused idempotency
  keys with different payloads. Keep the existing operations routes.
- Add a minimal Flask-served UI: overview/status, ranked stocks with reasons,
  action approval queue, portfolio/journal, backtest form/history, config
  revisions and operation progress. Use existing CSS/assets only where they
  fit. Prefer server templates and small vanilla JS; live prices may refresh
  from a read-only backend endpoint.
- Use a local authenticated operator session with CSRF protection for browser
  mutations; do not put the operator token into HTML, JavaScript or local
  storage. Restrict bind address and provide clear stale/partial/error states.
- Gate: browser tests complete Day 0 → screen → inspect → propose → approve →
  paper fill → portfolio → backtest, including one failed job and cancellation.
  UI values reconcile with API and artifacts.

### 7. Cutover and release evidence

- Run a full read-only legacy import against copied data; compare counts,
  holdings, cash, realised P&L, configuration, rankings and backtest histories.
  Classify every discrepancy as corrected bug, intended rule change or defect.
- Test backup/restore and replay on Windows and Linux; run large-universe load
  and failure injection. Record operator runbook for token renewal, provider
  outage, jobs, corrupt artifacts and rollback.
- Gate: no unexplained financial delta, no missing active instrument/account,
  all critical tests and CI pass, minimal UI workflows pass, and release
  version/metadata/docs agree. Maintain a reversible legacy backup. Live
  broker execution requires a separate go-live review after paper observation
  and reconciliation, not automatic activation with the frontend.

## Agent handoff instructions

Use **Terra** for the domain-heavy PRs (phases 0–5) and **Luna** for bounded
API/UI/documentation work (phase 6) once the corresponding backend contracts
exist. Keep one PR/agent on a shared schema or domain module at a time. Give
each agent this file, the [current state](Current%20state.md), and the
[gap review](Design%20and%20implementation%20gap%20review.md). Do not ask an
agent to “finish the migration” in one change.

For each assigned PR, use this instruction template:

> Implement **phase N, named slice** from `docs/current/Implementation plan.md`.
> Read the phase's v3 files from Git history and the current v4 contracts.
> First add a compact behavior map and fixture for that slice. Implement
> through the existing package boundaries and immutable/ledger authorities.
> Include migrations, API contracts, failure behavior, recovery behavior and
> tests stated in the phase gate. Do not modify unrelated dirty work, revive
> mutable v3 tables as authorities, or enable live broker submission. Update
> the capability matrix and runbook for the actual result. Run Python 3.13
> tests, Ruff, mypy, Bandit, lock/package checks and any slice-specific replay
> or browser tests. Report exact files, acceptance evidence and remaining
> deltas; stop if a missing provider right or unreconciled financial mapping
> would make the result misleading.

Suggested first assignments:

1. **Terra 0A:** v3 route/table inventory, read-only import mapping and
   anonymised fixtures; no production DB writes.
2. **Terra 1A:** exchange/Kite instrument identity plus dated alias snapshots
   and the exact-versus-proxy turnover contract.
3. **Terra 1B:** dated liquidity universe and benchmark ingestion, after 1A.
4. **Terra 2A:** Kite market-data backfill, validation and recovery, with
   adjustment-basis evidence.
5. **Terra 3A–5B:** one independently testable factor, ledger or
   backtest slice per PR following the gates above.
6. **Luna 6A:** typed read APIs and minimal overview/ranking templates after
   the research query contract is stable; **Luna 6B:** action/portfolio and
   backtest screens only after those commands and projections are stable.

Do not parallel-edit `catalog.py`, `jobs.py`, `ledger.py`, `run.py` or the same
migration namespace. An integration pass after each PR must confirm source
lineage, API/UI values and tests before the next dependent assignment.

**Copy-ready first handoff to Terra:**

> Deliver phase 0A only. Inspect v3 routes, models, formulas and UI behavior
> from Git `HEAD` and `docs/archive/v3`; inspect v4 packages and operations
> routes in the current working tree. Add a route-by-route capability matrix
> with v3 inputs/outputs, v4 owner, parity status, API/UI replacement and
> acceptance fixture. Design the legacy-to-v4 mapping for instruments,
> market bars, strategy configuration, rankings, actions, manual trades,
> cash events and backtests. Implement a read-only discovery/import-preview
> command that accepts **copies** of legacy databases, recognizes missing or
> unknown schemas, and reports counts, hashes, identity collisions and
> unmapped rows without writing to source files or `system.db`. Use synthetic
> anonymised fixtures, including split, symbol change, duplicate NSE/BSE
> listing, partial fill and FIFO sale. Test repeated previews and verify source
> hashes are unchanged. Do not change live routes, strategy logic or real
> account data in this PR. Report exact reconciliation gaps and the next
> smallest implementation slice; run the repository's existing quality gates.
