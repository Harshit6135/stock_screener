# Remaining implementation work

Last validated: 2026-09-19

This is the only active implementation backlog. Completed work is deliberately
omitted. Current code and tests are authoritative; archived V3 material is
historical reference, not a current requirement.

The live `instance/system.db` currently has
zero market bars, indicators, daily scores, weekly rankings, and backtest runs.
It contains 1,744 universe rows left by an interrupted build, so those rows are
inactive and are not accepted as a completed universe.

## Backend correctness blockers

### Restore the static-type validation gate

`mypy src run.py` does not currently pass. Most findings are unchecked
`object`/JSON/SQLite boundary types across the backtest, ledger, market,
research, and web layers. Add typed payload and row boundaries and make mypy a
required validation gate; do not suppress these findings globally.

### Validate the full historical rebuild

No completed provider-backed rebuild from 2015-01-01 exists in the current
database. Run the day-zero universe job to replace the inactive 1,744-row
interrupted build, then download and validate the full market
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
- Add a Kite execution-intent route, explicit fill provenance, broker trade and
  order identifiers, and complete fee/tax fields.
- Finish Kite holdings/orders/trades import and deduplicated reconciliation
  with manually confirmed transactions.
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

1. Manual and Kite-confirmed transactions share one deduplicated real ledger.
2. A strategy composed from supported indicators and operations runs and
   backfills without Python changes.
3. Pandas TA conformance, parity, no-look-ahead, and performance gates pass.
4. The 2015-present rebuild is validated.
5. Both strategies produce validated rankings and backtests from rebuilt data.
6. The indicator/strategy UI and deferred dashboard refresh work are completed
   in the later UI workstream.
