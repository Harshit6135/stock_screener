# Remaining implementation work

Last validated: 2026-09-19

This is the only active implementation backlog. Completed work is deliberately
omitted. Current code and tests are authoritative; archived V3 material is
historical reference, not a current requirement.

Validation baseline: `125 passed`. The live `instance/system.db` currently has
zero market bars, indicators, daily scores, weekly rankings, and backtest runs.
It contains 1,744 universe rows left by an interrupted build, so those rows are
not accepted as a completed universe.

## Backend correctness blockers

### Confirmed fills only in the real portfolio

`ActionJobs.process()` still converts approved strategy decisions into ledger
fills using stored model/historical prices. That violates the real-portfolio
boundary. Change proposal processing to create an execution intent only.
Holdings may change only from:

- complete manually confirmed execution facts; or
- Kite-confirmed/reconciled trades.

Add explicit transaction provenance, broker trade/order identifiers, and a
manual-versus-Kite reconciliation path so the same trade cannot be posted
twice. Backtest fills must remain isolated from the portfolio ledger.

### Atomic fixed-universe publication

The ₹500 crore YFinance screen retains existing members and adds newly eligible
stocks, but `universe_membership` has no completed-build marker. A failed first
scan can therefore leave a non-empty partial universe that market refresh will
accept.

Required work:

- Build a candidate snapshot separately from the active membership.
- Publish/activate it atomically only after the scan reaches a terminal state.
- Record resolved, unresolved, selected, threshold, source, and completion
  metadata.
- Keep the previous completed universe active when a later refresh fails.
- Clear the current untrusted 1,744-row partial build and rerun day zero.

### Validate the full historical rebuild

No completed provider-backed rebuild from 2015-01-01 exists in the current
database. After the universe is rebuilt, download and validate the full market
history, then generate features, scores, and rankings for both strategies.
Validation must include coverage gaps, benchmark coverage, new listings,
delisted/held instruments, duplicate ISINs, ranking counts, and sample numerical
checks before backtests are trusted.

## Strategy engine work

### Replace custom whole-strategy dispatch with a generic DAG executor

The two seed YAML files are active and revision-aware, but each still selects a
large Python implementation through `calculation.instrument_implementation`.
Adding a materially new strategy therefore still requires Python.

Implement execution of the validated YAML indicator/operation graph:

- Resolve approved Pandas TA, custom, and built-in nodes.
- Validate dependencies and reject cycles or unknown references.
- Execute instrument, benchmark-relative, and cross-sectional nodes.
- Apply declarative eligibility, penalties, factors, modifiers, and scoring.
- Include normalized node identities and input snapshots in lineage.
- Require Python only for a genuinely new reusable custom calculation.

After parity is accepted, reduce `custom.momentum_quality_features` and
`custom.relative_strength_features` to reusable calculations that Pandas TA or
the declarative operation set cannot represent.

### Complete Pandas TA acceptance testing

The adapter currently exposes eight approved studies, while focused coverage
only proves deterministic EMA behavior. Add tests for every approved study:

- parameter defaults and boundaries;
- input and output schemas, including multi-output mapping;
- warm-up/null behavior, constant data, gaps, and zero volume;
- non-finite rejection and deterministic repeated execution;
- truncation/append no-look-ahead behavior;
- numerical parity for both migrated strategies; and
- cold/warm performance for representative universe backfills.

Pin and record the resolved Pandas TA version in lockfile, artifact lineage,
and the support catalogue. Unsupported installed functions must not be exposed
as supported merely because they are callable.

### Generic history planning

The pipeline accepts active strategy IDs and stores revision-aware results, but
it is limited to 365 days and defaults to weekdays rather than an authoritative
exchange calendar. Add a revision-based history planner that:

- calculates warm-up requirements;
- divides multi-year provider work into bounded child jobs;
- uses actual exchange sessions;
- resumes only missing market/features/scores/rankings;
- checkpoints long stages and verifies completeness; and
- supports a newly defined strategy without registering new job kinds.

## Portfolio and execution work

- Establish `portfolio` as the default account identity for new workflows.
- Add explicit fill provenance and complete fee/tax fields.
- Finish Kite holdings/orders/trades import and reconciliation.
- Keep live Kite order placement disabled until a separate rollout policy,
  kill-switch procedure, and real-account acceptance test are approved.
- Retain operator-reviewed delisting liquidation; automatic broker liquidation
  remains a separate safety decision.
- Validate exact tax/fee threshold behavior with complete historical inputs.

## UI work intentionally deferred

- Build a strategy editor with YAML preview/import/export, validation, revision
  history, activation, dependency preview, and backfill progress.
- Build an Indicators page from `GET /api/v2/indicators/catalog`, including
  support/test status and manual-effort explanations.
- Redesign portfolio and action pages around confirmed real transactions and
  execution intents.
- Stop full-dashboard refreshes when index quotes change.
- Update index widgets incrementally and restore the animated running line with
  up/down colors while preserving inputs, scroll position, and open panels.

## Deployment and optional future work

- Add process/service supervision for long-running intraday streaming.
- Add multi-user identity, RBAC, encrypted per-user credentials, and TLS before
  any shared/network deployment. These are intentionally unnecessary for the
  current loopback-only local application.
- Expand performance diagnostics beyond the existing return, CAGR/XIRR,
  drawdown, Sharpe/Sortino/Calmar, annual-return, attribution, stress, and
  sanity outputs.
- ML/RL factor optimization, leakage-safe out-of-sample evaluation, and
  promotion governance remain optional future research rather than release
  requirements.

## Definition of done

The active backlog is complete only when:

1. Strategy proposals cannot create portfolio fills.
2. Manual and Kite-confirmed transactions share one deduplicated real ledger.
3. A strategy composed from supported indicators and operations runs and
   backfills without Python changes.
4. Pandas TA conformance, parity, no-look-ahead, and performance gates pass.
5. The fixed universe is atomically published and the 2015-present rebuild is
   validated.
6. Both strategies produce validated rankings and backtests from rebuilt data.
7. The indicator/strategy UI and deferred dashboard refresh work are completed
   in the later UI workstream.
