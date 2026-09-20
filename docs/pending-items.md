# Pending items

Last reviewed: 2026-09-20

This document contains only incomplete work. Completed plans and historical V3
notes are intentionally not retained as active documentation.

## Data rebuild and validation

- Validate the completed fixed-universe build and retain its membership snapshot
  as the documented day-zero survivor-biased baseline.
- Complete and validate Kite market history from `2015-01-01` through the
  latest completed session.
- Validate coverage gaps, benchmark coverage, IPO/pre-listing ranges, delisted
  and held instruments, token changes, duplicate ISINs, and NSE preference.
- Run the staged bulk indicator, percentile, score, and ranking rebuild for
  both active strategies from the validated market data.
- Record stage timings and peak memory for representative one-year ranges;
  investigate any regression that reintroduces per-date history loading or
  rolling-window recalculation.
- Validate representative numerical samples and ranking counts before treating
  backtests as strategy evidence.

## Generic strategy execution

- Replace complete-strategy Python dispatch with execution of the validated
  YAML indicator and operation DAG.
- Resolve approved Pandas TA, built-in, and reusable custom nodes.
- Reject dependency cycles, unknown references, and incompatible outputs.
- Execute instrument, benchmark-relative, and cross-sectional stages.
- Apply declarative eligibility, penalties, factors, modifiers, and scoring.
- Include normalized node identities and all input snapshots in lineage.
- Require Python only when a genuinely new reusable calculation is needed.
- Reduce the two current custom complete-strategy implementations after parity
  with the generic executor is proven.

## Pandas TA acceptance

- Test all eight approved studies for defaults, parameter boundaries, input
  schema, output mapping, warm-up/null behavior, gaps, constant series, zero
  volume, and non-finite rejection.
- Add deterministic repeat and append/truncation no-look-ahead tests.
- Establish numerical parity for both migrated strategies.
- Benchmark cold and warm execution on representative universe history.
- Record the resolved package and adapter versions in artifact lineage and the
  indicator catalogue.
- Build the UI Indicators page from `/api/v2/indicators/catalog`, including
  support/test status and explanations for calculations requiring manual code.

## Historical planning

- Replace the 365-day pipeline limit with a revision-aware history planner.
- Derive warm-up requirements from the active strategy revision.
- Split multi-year work into bounded resumable jobs.
- Use an authoritative exchange calendar instead of weekday expansion.
- Resume only missing market, feature, score, and ranking ranges.
- Verify stage completeness before allowing dependent work.

## Portfolio and execution

- Make `portfolio` the default account identity in all user-facing workflows.
- Add a complete strategy-proposal-to-Kite-execution-intent route.
- Store explicit transaction provenance, broker trade/order IDs, fees, taxes,
  and actual execution timestamps on reconciled transactions.
- Complete holdings, orders, and trades import with deduplication between Kite
  and manually confirmed transactions.
- Keep live order placement disabled until kill-switch procedures and a
  real-account acceptance test are approved.
- Retain human-reviewed delisting liquidation; automatic broker liquidation is
  a separate safety decision.
- Validate historical fee and tax thresholds with complete source data.

## Static typing and code quality

- Make `mypy src run.py` pass without globally suppressing errors.
- Replace unchecked `object`/JSON/SQLite boundaries with typed payload and row
  models across backtest, ledger, market, research, and web layers.
- Add the passing type check to the required validation gate.

## UI redesign

- Build a strategy editor with YAML preview/import/export, validation, revision
  history, activation, dependency preview, and backfill progress.
- Redesign portfolio and action pages around confirmed transactions and
  execution intents.
- Stop full-dashboard redraws when index quotes update.
- Update only index widgets and restore the animated running line with up/down
  coloring while preserving form values, scroll position, and open panels.

## Deployment and optional research

- Add process/service supervision for long-running intraday streaming.
- Before any shared/network deployment, add identity, RBAC, encrypted per-user
  credentials, TLS, and deployment hardening. These are not needed for the
  current loopback-only application.
- Expand performance diagnostics only where they add information beyond the
  existing return, CAGR/XIRR, annual returns, drawdown, risk ratios,
  attribution, stress, and sanity outputs.
- Treat ML/RL optimization, leakage-safe out-of-sample evaluation, and model
  promotion governance as optional future research.

## Completion criteria

The current major redesign is complete when:

1. the 2015-present data and both strategy histories are rebuilt and validated;
2. a strategy composed from supported nodes runs without strategy-specific
   Python changes;
3. Pandas TA conformance, parity, no-look-ahead, and performance gates pass;
4. manual and Kite-confirmed transactions share one deduplicated real ledger;
5. the static type gate passes; and
6. the deferred strategy, indicator, portfolio, and dashboard UI work is done.
