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

## Workflow parity at the reviewed V4 commit

| V3 workflow | V4 backend at `f26cc48` | V4 frontend at `f26cc48` | Parity work to prove |
|---|---|---|---|
| Initialize and screen NSE/BSE instruments; refresh latest and historical prices | Kite instrument sync, bar jobs, token history and coverage exist. A completed equivalent to V3's YFinance-enriched day-0 master and price/market-cap screen was not established in the committed pipeline. | The pipeline page submits broad jobs and displays status; it lacks V3's per-step controls and streaming console. | Prove a dated eligible universe, provider failure handling, incremental refresh, and a user-visible run result. |
| Calculate indicators, factors, percentiles, scores and weekly rankings for both strategies | Research jobs and artifacts exist. Strategy 2 is provisional. Indicator composition, factor formulas and weights remain in Python. | The overview displays rankings; V3-style calculation controls and intermediate-result inspection are incomplete. | Compare both strategies on frozen input data and expose the results and errors needed to operate them. |
| Generate, edit, approve, reject and process weekly and midweek actions | Paper proposals, amendments, bulk decisions and pyramiding exist. The stop and execution policies are not yet equivalent to V3. | Basic proposal review exists; manual entry uses JSON and there is no equivalent inline edit/review flow. | Verify weekly, vacancy, pyramid, stop, edit, approval, rejection and processing cases, including partial sells. |
| View holdings, cash, capital events, journal, risk, equity history and live prices | Ledger, transfers, valuations and journal exist. The portfolio ticker uses the latest stored daily market bar; its SSE route delivers one snapshot, not V3's live quote stream. | Portfolio output is primarily raw JSON, without V3's holdings table, charts and trade controls. | Verify accounting after buys, sells and transfers, then make each result usable from the browser. Treat live quotes as a separate parity case. |
| Run backtests with V3 controls; inspect reports and history | A different replay engine and saved reports exist. V3 daily-stop and midweek-buy options are not carried through as equivalent controls. | Submission and report display are JSON-oriented, without V3's result charts and tables. | Compare execution timing, options, trades, costs, tax estimates, metrics and saved history on frozen fixtures. |
| Edit strategy configuration and run maintenance | Dated approvals for capital/risk settings exist. Indicator selection, factor composition and weights are not externalized. | Active settings can be viewed, but the V3 editing workflow is absent. | Provide a complete configuration workflow and distinguish risk settings from research strategy definitions. |

The committed V4 frontend is implemented in
[`dashboard_web.py`](../../src/application/dashboard_web.py). The V3 browser
baseline is the dashboard template and scripts at `dabff59`.

## Concrete end-to-end blockers to resolve

1. **Pipeline dependencies are not enforced through market-data completion.**
   [`ResearchPipelineJobs.submit`](../../src/application/pipeline_jobs.py)
   queues reference, refresh and daily research jobs. The refresh planner
   [`schedule`](../../src/application/market_refresh.py) creates per-symbol bar
   jobs only when the refresh job runs. Those bar jobs can therefore be queued
   after daily research jobs. Reference reconciliation is also submitted before
   refresh. Stage success must depend on completion and quality of the actual
   upstream bar work, not merely successful scheduling.
2. **A submitted job needs an operating worker.** The web server in
   [`run.py`](../../run.py) does not run a continuous job worker; the CLI offers
   `work-once`. An end-to-end operator flow must specify how the worker stays
   active, restarts and reports a terminal failure.
3. **Research and execution differences need measured parity.** In particular,
   Strategy 2 provisional inputs, the action stop policy, and V3 backtest
   switches cannot be declared equivalent from matching route names or a
   successful HTTP response alone.
4. **Frontend completion must be checked as workflows.** A page existing at
   `/actions`, `/backtest`, `/pipeline`, `/configs` or `/portfolio` is not enough
   if it cannot perform and explain the corresponding V3 task.

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
