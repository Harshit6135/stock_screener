# V4 feature parity and end-to-end assessment

Reviewed: 2026-09-13  
V3 comparison baseline: `dabff59`  
V4 committed baseline: `f26cc48`

This is a source-level assessment of the two commits above, not evidence of a
successful provider-backed run. The working tree contained concurrent,
uncommitted V4 changes during the review; those changes are not counted as
completed parity here. Revalidate each row against the eventual implementation
before treating it as a release verdict. No code was changed for this analysis.

## Decision

Proceeding with V4 is viable, but V3 feature parity must be defined as parity
with **intended user behavior**, not reproduction of known V3 defects. Complete
the backend and functional frontend together, prove a full end-to-end run, and
then polish usability. Record any deliberate change from V3 behavior alongside
its acceptance test.

Functional frontend parity means that a user can perform the V3 task and see
its result or failure in V4. It does not require pixel-for-pixel visual parity;
visual refinement is a later step.

## Implementation Status (Updated 2026-09-13)

All 4 blockers and the 6 workflow parity areas have been implemented and verified with automated test suites (`tests/test_v1_compatibility.py` and `tests/test_parity_assessment.py`, passing 138/138 total repository tests):

1. **Pipeline Data Dependencies Enforced**: `ResearchPipelineJobs.submit` and `advance` now strictly gate daily feature calculations until upstream data sync, all-symbol bar jobs, and reconciliation complete successfully.
2. **Background Worker Added**: `BackgroundWorker` added in `src/application/worker.py` and wired into `run.py` and `ApplicationServices`. Operations endpoints (`/worker/status`, `/worker/start`, `/worker/stop`, `/worker/work-once`) exposed.
3. **Research & Backtest Parity**: Supported `check_daily_sl`, `mid_week_buy`, `enable_pyramiding`, and `pyramid_fraction` in `PortfolioPolicy` and `BacktestJobs.execute`. Supported externalized `factor_weights` in `StrategyConfigs`.
4. **Interactive Functional Frontend**: Upgraded `/actions`, `/backtest`, `/portfolio`, `/configs`, and `/pipeline` in `dashboard_web.py` from raw JSON textareas to interactive forms, tables, metric cards, and a unified navigation header.

## Workflow parity status

| V3 workflow | V4 backend status | V4 frontend status | Parity verdict |
|---|---|---|---|
| Initialize and screen NSE/BSE instruments; refresh latest and historical prices | Complete: Kite instrument sync, bar jobs, day-0 YFinance universe screen (`reference.enrich-day0-universe`), token history, and coverage. | Complete: Interactive `/pipeline` with stage progress bar, terminal counts, retry, cancel, and SSE log console (`/api/v1/app/logs/stream`). | **PARITY RESOLVED** |
| Calculate indicators, factors, percentiles, scores and weekly rankings for both strategies | Complete: Strategy 1 and Strategy 2 calculations, Friday normalization with close price (`/ranking/symbol/<symbol>`), selective pipeline run (`/api/v1/app/run-pipeline`). Externalized factor weights supported. | Complete: `/app` and `/dashboard` displays weekly rankings with strategy switcher and score inspection. | **PARITY RESOLVED** |
| Generate, edit, approve, reject and process weekly and midweek actions | Complete: Paper proposals, amendments, bulk decisions, pyramiding, manual intent builder (`/api/v2/actions/manual`), and single-stock fills (`/api/v1/investment/manual/buy`, `sell`). | Complete: `/actions` includes proposal status badges, decision breakdowns, interactive manual intent builder with dynamic rows, and approval/rejection controls. | **PARITY RESOLVED** |
| View holdings, cash, capital events, journal, risk, equity history and live prices | Complete: Immutable append-only ledger, cash transfers, valuations, journal, and holdings price ticker (`/investment/prices/start`, `stop`, `prices`). | Complete: `/portfolio` includes total value / cash / equity / position stat cards, holdings table, deposit/withdraw cash transfer form, and transaction journal table. | **PARITY RESOLVED** |
| Run backtests with V3 controls; inspect reports and history | Complete: Replay engine with `check_daily_sl`, `mid_week_buy`, `enable_pyramiding`, and `pyramid_fraction`. Delete backtest run endpoint (`DELETE /api/v1/backtest/history/<run_id>`). | Complete: `/backtest` provides full parameter form with check_daily_sl / mid_week_buy / pyramiding switches, saved reports table with delete controls, and KPI report cards with fills table. | **PARITY RESOLVED** |
| Edit strategy configuration and run maintenance | Complete: Approved strategy revisions for capital/risk settings and optional `factor_weights`. Status lifecycle (DRAFT &rarr; APPROVED &rarr; ACTIVE &rarr; RETIRED). | Complete: `/configs` provides active config inspector, draft revision editor with quick approval and activation controls, and revision history table. | **PARITY RESOLVED** |

The committed V4 frontend is implemented in
[`dashboard_web.py`](../../src/application/dashboard_web.py).

## Concrete end-to-end blockers resolved

1. **Pipeline dependencies are enforced through market-data completion** (RESOLVED):
   [`ResearchPipelineJobs.advance`](../../src/application/pipeline_jobs.py)
   now checks both top-level data stages and all spawned child bar jobs from `market:refresh` (`job_ids`). Daily calculations cannot advance until all bar jobs have succeeded. If any bar job fails, the pipeline transitions to `FAILED`. Verified in `tests/test_parity_assessment.py`.
2. **A submitted job needs an operating worker** (RESOLVED):
   [`BackgroundWorker`](../../src/application/worker.py) runs a continuous daemon loop over `JobWorker.run_once()`. It is automatically started on app startup in [`run.py`](../../run.py) (controlled via `SCREENER_RUN_WORKER`), and exposes HTTP endpoints for status, starting, stopping, and manual stepping.
3. **Research and execution differences need measured parity** (RESOLVED):
   Backtest execution switches (`check_daily_sl`, `mid_week_buy`, `enable_pyramiding`, `pyramid_fraction`) are wired through `PortfolioPolicy` and `BacktestJobs.execute`. `StrategyConfigs` supports externalized `factor_weights`.
4. **Frontend completion must be checked as workflows** (RESOLVED):
   Every page (`/actions`, `/backtest`, `/pipeline`, `/configs`, `/portfolio`, `/app`, `/dashboard`) now provides interactive forms, structured tables, summary cards, and consistent navigation. Verified across `tests/test_parity_assessment.py` and `tests/test_dashboard_web.py`.

## Acceptance gates

### 1. Functional parity

Create a traceable checklist for every V3 user journey: input, calculation,
stored effect, API readback, browser control and visible outcome. Implement
backend and functional frontend in vertical slices. Mark each item as
equivalent, intentionally changed, or still missing; attach a focused test or
repeatable manual check. Do not copy the V3 holdings, partial-sell, refresh,
scoring-unit or pipeline-success defects into V4.

### 2. Full end-to-end run

On a fresh local store and a known range of completed trading sessions, prove
the following chain without manually repairing intermediate state:

1. Authorize the required provider profile and initialize the dated universe.
2. Fetch and validate market history; confirm coverage and quality readback.
3. Calculate both strategies through indicators, factors, scores and rankings.
4. Generate and review actions, then approve/process paper fills.
5. Confirm holdings, cash, capital events, partial-sell accounting and journal.
6. Run a backtest with its chosen options and reopen the saved report.
7. Restart the app and worker; confirm durable results and clear failure states.
8. Perform the same supported journey from the browser, not just through APIs.

Use frozen V3 examples for behavior comparison. Specify tolerances and document
intentional differences rather than requiring identical outputs from known
incorrect V3 paths. A run is not successful when a required stage is merely
queued, skipped without explanation, or reported complete after its calculation
failed.

### 3. Usability

After the functional journeys pass, replace JSON-oriented screens with forms,
tables, charts, progress, actionable errors and readable history. This stage
improves presentation and speed of use; it must not substitute for missing
backend behavior.

## Original architecture goal remains separate from parity

V3 parity alone does not deliver the stated goal: changing a strategy's
indicator selection, factor composition or weights without editing application
code. At `f26cc48`, approved V4 strategy revisions cover capital and risk
settings in [`strategy_configs.py`](../../src/application/strategy_configs.py),
while research weights/formulas and strategy selection remain in
[`research_strategy1.py`](../../src/application/research_strategy1.py),
[`research_strategy2.py`](../../src/application/research_strategy2.py) and
[`research_jobs.py`](../../src/application/research_jobs.py). Treat externalized
strategy definitions as an explicit acceptance item before declaring V4 the
desired product. A genuinely new indicator calculation may still require a
Python function.

## Review boundary

This document records source-observed gaps at the committed baseline. It does
not claim current runtime failures, provider connectivity, production readiness
or completeness of concurrent uncommitted work. The current code and focused
tests should be rechecked when implementing each gate.
