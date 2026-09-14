# V4 parity and end-to-end reassessment

Reviewed: 2026-09-13  
V3 comparison baseline: `dabff59`  
Current V4 working baseline: `40d3cab` (`Codex Enhancement`)

## Scope and method

This is a source-level re-review. The V3 and V4 source, current browser code,
compatibility routes, job orchestration, configuration handling, and relevant
tests were read in full before reaching the conclusions below. No source code
was changed. The assessment separates code that exists from workflows that are
actually connected and verifiable.

`pytest -q` passed: **138 passed**. That proves the tested unit and route
contracts, but it is not end-to-end parity evidence. In particular,
`test_v1_compatibility.py` builds a small separate Flask application and does
not exercise `run.create_app`, the real `/dashboard` page, a worker-run job, or
provider-backed data. `test_dashboard_web.py` checks that V4 pages return HTML;
it does not run their browser workflows. `test_parity_assessment.py` checks
isolated pipeline scheduling and configuration storage, not their integration
with the V3 dashboard compatibility API.

## Corrected decision

V4 has useful capabilities that V3 did not have, but it does **not** currently
have proven V3 feature parity or a working end-to-end path. Do not begin
usability work or further feature expansion yet. First make a small set of
vertical workflows work from the actual browser UI through persisted results,
then test them on completed market dates with a worker and configured provider.

The required product boundary remains:

- A new indicator calculation may require a Python function.
- Strategy indicator selection, factor composition, weights, and ordinary
  strategy parameters must be data/configuration, not code edits.

## What V4 adds beyond V3

The following capabilities are present in V4 source and are meaningful reasons
to continue with it once the integration gaps are fixed:

| Priority | V4 capability absent or materially weaker in V3 | Current evidence | Why it matters |
|---|---|---|---|
| P0 | Durable queued jobs, worker, cancellation, retry and job status | `jobs.py`, `worker.py`, `web.py` | Lets long-running provider and research work run outside HTTP requests. |
| P0 | Explicit research pipeline model with staged dependencies | `pipeline_jobs.py` | Provides a sounder basis for orchestrating data, daily calculations and weekly rankings. |
| P0 | Immutable strategy configuration revisions and approved effective dates | `strategy_configs.py`, `configs_web.py` | A suitable base for changing ordinary strategy settings safely. |
| P0 | Immutable portfolio ledger, cash events, fills, valuations and journal | `portfolio_*`, `portfolio_web.py` | Replaces mutable portfolio calculations with auditable accounting. |
| P1 | Paper action proposals, amendment history, approvals and manual intents | `actions.py`, `actions_web.py` | Separates a trade decision from its execution record. |
| P1 | Replay/backtest engine with artifacts and saved reports | `backtest_jobs.py`, `backtests_web.py` | Supports reproducible backtests and stored reports. |
| P1 | Corporate-action adjustment path, reference artifacts and data-quality artifacts | related V4 application modules | Supports more defensible historical research. |
| P2 | Dedicated V4 operator pages for actions, portfolio, backtests, configs and pipeline | `dashboard_web.py` | Gives a foundation for a usable operator UI once its routes are corrected. |

These are implementation assets, not parity verdicts.

## Reverified workflow status

| User workflow | What exists | Reverified result |
|---|---|---|
| V3 dashboard | `run.py` serves the legacy `templates/dashboard.html` at `/dashboard`; the V1 compatibility blueprint is registered. | **Broken parity.** The legacy JavaScript calls several routes that do not exist or use incompatible methods/payloads. |
| V4 operator pages | `/app`, `/actions`, `/backtest`, `/portfolio`, `/configs`, `/pipeline` are served by `dashboard_web.py`. | **Partial.** Pages render and several V2 flows are wired, but the configuration page uses invalid V2 routes and request shapes. |
| Initialize and screen instruments | Sync and a YFinance enrichment loop exist. | **Not parity.** The enrichment loop counts responses only; it does not persist enrichment/market-cap/price, mark eligibility, or exclude ineligible instruments. Broad exceptions also hide failures. |
| Market-data refresh then research calculation | V4 has refresh jobs and research handlers. V1 `run-pipeline` exists. | **Blocked.** The V1 route schedules work and immediately reports each requested stage as successful. It uses the current UTC date, while V4 research/backtests require completed dates. It does not wait for refresh child jobs, calculation jobs, or ranking jobs. |
| Indicators, factors, percentiles, scores and rankings | Strategy 1 and Strategy 2 calculations and weekly rankings exist. | **Partial.** The compatibility indicator GET returns only latest raw close/volume; POST does not persist indicators and DELETE reports zero. The patch endpoint queues a calculation but does not apply a supplied indicator patch. |
| Rankings in the V1 dashboard | Ranking routes exist. | **Partial.** The top route derives the prior Friday from today; symbol response reads the latest close rather than the close on the requested ranking date. |
| Generate, edit, approve, reject and process actions | V4 proposal and ledger services exist; V1 wrappers exist. | **Broken parity.** Legacy V3 UI calls bulk approval, reject-all and date/process routes absent from V1 compatibility. Its action edit sends units and execution price, but the compatibility update ignores both and only approves/rejects a proposal. |
| Manual buys and sells | V1 manual fill routes call the V4 ledger. | **Partial.** They bypass V3 configuration behavior and create an absent account with hard-coded capital. They are not a demonstrated replacement for the V3 flow. |
| Holdings, cash, journal, history and prices | V4 ledger/valuation endpoints exist. | **Partial.** V1 summary derives risk as a flat 5% and labels gain percentage as XIRR; history returns one point and trade journal returns an empty list. V1 ticker is a snapshot of latest stored bars, not live provider prices. Legacy UI also calls missing capital-event, price-sync, start/stop ticker and live-price routes. |
| V4 portfolio page | Valuation, journal and cash transfer are wired. | **Partial.** Ticker response contains holdings but UI looks for `prices`, so it reports zero instruments. |
| Backtests | V4 engine supports several controls, stored runs and reports. | **Partial.** `BacktestJobs.execute` rejects `WEEKLY`, though the V4 UI offers it. The legacy V1 dashboard payload uses V3 field names such as `config_name`, so its backtest call is not translated to V4's required `strategy_id` schema. |
| Configuration editing | V4 stores supported config revisions and optional `factor_weights`. | **Broken functional UI and incomplete architecture.** `dashboard_web.py` calls `/api/v2/configs/active/<strategy>`, `/api/v2/configs/revisions`, and `/effective`; the actual API is `/<strategy>/active`, `/<strategy>/revisions`, and approval requires `{ "effective_from": ... }`. V1 configuration POST only echoes its body and does not save it; the legacy UI uses PUT. `factor_weights` are stored but research strategies do not read them. |
| Maintenance | V1 cleanup/recalculate routes exist. | **Not parity.** Cleanup deletes only market bars. Recalculate queues one calculation for the start date; it does not rebuild all dates, factors, scores, or rankings. |

## Exact frontend-to-API gaps found in the legacy dashboard

`static/js/dashboard.js`, used by the actual `/dashboard`, calls the following
routes that are not supplied with matching V1 behavior:

| Legacy call | Current mismatch |
|---|---|
| `/investment/capital-events` | No compatibility route. |
| `/investment/sync-prices`, `/start-ticker`, `/stop-ticker`, `/live-prices` | Compatibility exposes a static `prices` snapshot and differently shaped start/stop routes; it is not the legacy live ticker contract. |
| `/actions/dates`, `/actions/approve`, `/actions/reject-all`, `/actions/process` | No matching compatibility routes. |
| `PUT /config/<name>` | Compatibility has GET/POST only, and POST does not persist. |
| V3 action `PUT /actions/<id>` with units and execution price | Compatibility ignores those edits and only changes proposal decision status. |
| V3 backtest request | Compatibility forwards the V3 body directly to V4, whose accepted schema requires `strategy_id` and rejects unsupported fields. |

This makes `/dashboard` a rendered legacy screen, not a working parity frontend.

## Configuration architecture verdict

The current revision made one useful move: `StrategyConfigs` validates and
stores an optional `factor_weights` map. It is still not enough for the stated
goal. `research_strategy1.py` and `research_strategy2.py` do not read it; their
formulas, factors and indicator composition remain in Python. Therefore a
saved configuration can record weights without changing research output.

The smallest appropriate target is a versioned strategy-definition schema that
contains strategy-to-indicator dependencies, factor composition and weights.
The calculation registry can map an indicator name to its Python function.
Validation must reject unknown indicators/factors and incompatible parameters.
Research and backtests must load the approved definition and record its
revision/artifact in every output. This preserves code for genuinely new
indicator functions while removing code edits for composition and weights.

## Priority order before any usability work

1. **Make one V3-equivalent completed-date pipeline real.** Submit it, execute
   it with a worker, wait for market child jobs, calculate both strategies,
   rank, and verify persisted outputs. Do not return success until terminal
   results are known.
2. **Choose one browser surface.** Either complete the V1 compatibility
   contract used by `/dashboard`, or retire it and migrate users to V2 pages.
   Keeping both partial surfaces is the immediate source of complexity.
3. **Repair configurations as a vertical slice.** Correct V2 page routes and
   request bodies, make V1 behavior deliberate, and wire approved
   strategy-definition data into research and backtests.
4. **Complete portfolio/action behavior.** Use real ledger calculations for
   risk/history/journal, define action amendments and bulk processing, and
   prove manual and proposed fills through UI readback.
5. **Complete backtest parity.** Align supported frequencies and translate or
   replace the V3 input schema. Test report persistence and reopening.
6. **Add workflow tests.** Use `create_app`, a temporary store and a controlled
   completed-date fixture. Each test should exercise browser/API input, queued
   work, persisted effect and readback. Rendering and scheduling tests remain
   useful but cannot be the parity gate.

## End-to-end acceptance evidence required

On a fresh temporary data directory and known completed sessions, prove:

1. Instrument sync, persisted screening decision and market-bar coverage.
2. Worker-completed research output for both strategies and weekly rankings.
3. Browser readback of those rankings, action generation, approval, processing
   and ledger/journal result.
4. Configuration revision that changes a supported factor weight or composition
   and demonstrably changes the recorded research definition used by output.
5. Backtest submission, completed job, saved report, reopen after restart.
6. Clear failure response when a provider, a child job or a prerequisite fails.

Until these checks pass, the accurate status is: V4 contains valuable building
blocks, but feature parity and an end-to-end working application are incomplete.

## Implementation update — 2026-09-13

The first corrective implementation pass completed after this assessment:

- Pipeline coordination now defers its next pass while data or daily jobs are
  pending, instead of failing a pipeline solely because its prerequisites have
  not run yet. The V1 pipeline endpoint now returns `202` and a pipeline ID;
  it no longer reports queued work as completed.
- Approved configuration `factor_weights` are validated against the supported
  factor set, normalized, applied to percentile scoring, and recorded in
  feature, percentile and score artifacts. The V4 configuration page now uses
  the actual API paths and approval request shape, and exposes a weights JSON
  field.
- Weekly backtest frequency is now accepted by the API, policy and replay
  engine, matching the V4 browser control.
- The V1 compatibility layer now persists legacy configuration saves, provides
  the legacy ticker aliases, capital events, valuation history/journal readback,
  and bulk action approval/rejection/processing routes. These use V4 durable
  stores rather than placeholders.

Validation after these changes: **141 tests passed**. This includes real
`create_app` coverage for `/dashboard` and V1 configuration persistence. It
does not substitute for a run with real provider credentials and a completed
market-data range; that remains the final acceptance evidence above.
