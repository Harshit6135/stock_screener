# Target Architecture Implementation Plan

> **Status:** backend implementation in progress; legacy HTTP/UI bindings retired
>
> **2026-09-12 migration status:** the current v4 tree is in fact a breaking
> backend rewrite, but a production cutover has **not** been approved. The
> additive compatibility and old-route parity instructions below remain unmet
> target criteria, not claims of current capability. Existing deployments must
> retain their legacy baseline and data backups; migration posture and data
> reconciliation require an explicit operator decision.
>
> **Authority:** [Modular monorepo design](Modular%20monorepo%20design.md) is the target architecture. This
> plan implements it as a modular monolith; it does not split the application
> into networked services. `ARCHITECTURE_SIMPLIFICATION_PROPOSAL.md` remains a
> useful source of migration ideas, but its earlier three-package layout is
> superseded where it conflicts with the target design.

## Goals and non-goals

The programme moves the current Flask/three-SQLite application to a locally
operated, auditable system with immutable research artifacts, one transactional
portfolio ledger, a pure shared portfolio engine, and isolated backtests.

It preserves the current UI and REST surface during migration through adapter
endpoints and feature flags. No live broker order is enabled until the paper
workflow, reconciliation, recovery tests, and an explicit go-live checklist
pass. PostgreSQL, multi-user access, and cloud deployment are deferred until
the measured triggers in the target design apply.

## Delivery rules

- Make every phase additive. The legacy path remains readable until parity is
  demonstrated and a backup exists.
- Treat data, strategy, policy, engine, and fill-model versions as inputs.
  Never overwrite a published research artifact.
- Keep domain packages framework-free. Flask, SQLAlchemy, filesystem, Kite,
  yfinance, and SSE remain adapters wired only by `application`.
- Use one SQLite write coordinator for catalog and ledger mutations. A command
  has an idempotency key and expected aggregate version; repository methods do
  not commit independently.
- Require a migration test, replay/golden test, and rollback procedure before
  each destructive cutover.

## Workstreams and first artifacts

| Workstream | First deliverable | Current code to retire incrementally |
|---|---|---|
| Kernel/contracts | IDs, versioned Pydantic contracts, ports, errors, manifests | cross-layer ORM dictionaries |
| Research data | snapshot catalog, raw/normalized market artifacts, validation | mutable `market_data` through `ranking` tables |
| Portfolio | pure `PortfolioEngine`, accounting projections, golden scenarios | split action generator/lifecycle/processor state logic |
| Ledger/execution | transactional SQLite ledger, commands, audit trail, reconciliation | `personal.db` actions/holdings/summary as authorities |
| Backtesting | in-memory runner and run manifest/artifact publisher | shared `backtest.db` and mutable history folders |
| Application/ops | durable jobs, event stream, CLI, health/backup tooling | synchronous pipeline endpoints and global SSE queue |

## Phase 0 — Baseline, safety, and architecture seams

**Implementation status (2026-09-11):** framework-free import boundaries are
tested; private SQLite stores use versioned embedded migrations; Flask no
longer calls `create_all()` at startup; the backend binds loopback by default;
and every new mutating endpoint requires `SCREENER_OPERATOR_TOKEN`.

**Outcome:** a safe starting point and enforceable boundaries, with no business
behaviour change.

1. Add a `packages/` source layout with `platform_kernel` and empty public
   `api.py` modules for each target domain. Add an import-boundary test that
   permits only inward dependencies.
2. Define Pydantic command and result contracts: stable IDs, revisions,
   `Money`, `Quantity`, `InstrumentId`, `AsOfDate`, manifest, job, and domain
   errors. Reject invalid enums, non-finite prices, non-positive quantities,
   invalid transitions, and unknown instruments at the command boundary.
3. Add a migration policy: remove production `create_all()` startup mutation,
   establish reviewed Alembic migrations, migration-upgrade tests, and a
   documented backup/restore command for every SQLite file.
4. Fix immediate containment defects before new capability: bind local mode to
   loopback by default, put an operator token or local OS-user guard in front
   of mutating endpoints, make config updates filter by exact stable ID and
   optimistic revision, and disable destructive endpoints outside maintenance
   mode.
5. Create a characterization suite for current calculations and state changes:
   fixed OHLCV fixtures, strategy score/ranking fixtures, stop/gap cases,
   sizing, swaps, pyramids, FIFO, capital events, manual operations, and
   failure/retry cases.

**Exit criteria:** all current capabilities have a target owner; CI runs lint,
type checks, migration tests, and the characterization suite; restore is
verified from a clean working directory; no API mutates a configuration other
than its named ID.

## Phase 1 — Pure portfolio engine and accounting parity

**Implementation status (2026-09-11):** the framework-free engine and FIFO
accounting foundations are implemented with stop-gap and vacancy-buy scenarios.
They are not yet connected to legacy routes or declared parity-complete; swap,
pyramid, and all legacy golden scenarios remain required before cutover.

**Outcome:** one deterministic portfolio state machine used by paper/live
workflows and backtests.

1. Extract `portfolio_engine` as pure functions over `PortfolioState`, a
   `RankingSnapshot`, market bars, and `PortfolioPolicyRevision`.
2. Model decisions explicitly: `SELL`, `BUY`, `PYRAMID_ADD`, `SWAP`,
   `HARD_STOP_GAP_OPEN`, `HARD_STOP_INTRADAY`, and `NO_ACTION`. Return decision
   events plus next state; do not persist from this package.
3. Extract `portfolio_accounting` to derive cash, lots, FIFO matches,
   valuations, realised/unrealised P&L, risk, XIRR, and summaries from facts.
   Summaries become rebuildable projections.
4. Define the fill model once. In particular, a stop gap fills at the open and
   an intraday breach fills at the stop; make assumptions configurable and
   recorded in a fill-model revision.
5. Run legacy and new engines on the golden fixture set. Classify every delta
   as intended behaviour change, bad legacy behaviour, or defect before
   enabling the new engine for paper runs.

**Exit criteria:** deterministic replay passes for all golden scenarios;
backtest and paper decision outputs call the same engine; no engine import
depends on Flask, SQLAlchemy, provider SDKs, or filesystem code.

## Phase 2 — Reference and market-data lineage

**Implementation status (2026-09-11):** immutable JSON artifact publication,
checksummed manifests, reference-instrument snapshots, raw/normalized market
bar snapshots, persistent catalog lineage, and Kite/yfinance read-only adapter
ports are implemented. Provider credentials and token renewal remain explicit
operator concerns.

**Outcome:** reproducible, point-in-time inputs with explicit quality state.

1. Implement `reference_data` snapshots for instruments, ISIN aliases/token
history, calendars, universes, corporate actions, benchmarks, and fundamentals.
2. Implement `market_data` provider ports and adapters for Kite, yfinance, and
NSE/BSE imports. Persist raw provider responses separately from normalized,
adjusted bars.
3. Introduce an artifact catalog with immutable IDs, schema version, checksums,
upstream IDs, quality state, and supersession/revocation status.
4. Publish through a staging directory, validate counts/schema/checksum, then
atomically publish and record the catalog entry. Implement startup recovery for
orphaned staging data.
5. Replace in-place corporate-action refills with a corrected superseding
snapshot and an `InvalidationPlan` for affected features, rankings, and runs.

**Exit criteria:** a historical date resolves to its original universe,
benchmark, adjusted market bars, and quality status; a correction does not
overwrite prior inputs; one controlled replay matches the legacy data pipeline.

## Phase 3 — Versioned indicators, strategies, and research artifacts

**Implementation status (2026-09-11):** immutable indicator definitions and
configurations, strategy/policy revisions, and revision-keyed ranking snapshot
contracts are implemented. Legacy factor computation and ranking routes still
write their existing tables until artifact-parity adapters are added.

**Outcome:** factor changes are additive and historical rankings remain valid.

1. Create indicator definitions/configurations with declared inputs, warm-up,
parameters, output schema, implementation hash, and semantic revision.
2. Move strategy formulas to strategy revisions and register approved factors
declaratively. Keep the two existing strategies as frozen initial revisions.
3. Turn portfolio sizing/stops/rebalance settings into immutable policy
revisions. Replacing a value creates a successor revision; activation is an
audited state transition.
4. Publish feature, percentile, score, and ranking snapshots keyed by exact
revision and upstream snapshot IDs—not just date plus strategy name.
5. Provide compatibility adapters so existing ranking routes read the active
snapshot while new endpoints expose snapshot IDs and explanations.

**Exit criteria:** two revisions may rank the same historical date side by
side; changing a weight cannot change an existing ranking; every ranking member
explains eligibility, factors, score, and inputs.

## Phase 4 — Isolated research jobs and backtests

**Implementation status (2026-09-11):** an in-memory backtest driver,
immutable run artifact publisher, SQLite WAL job store, idempotent job
submission, lifecycle transitions, and cursor-based per-job events are
implemented. Worker orchestration and legacy-route cutover remain pending.

**Outcome:** concurrent and repeatable research with no shared scratch state.

1. Replace the shared backtest database with an in-memory state driver over
the pure engine and accounting package.
2. Create `BacktestRunManifest` containing all snapshot IDs, strategy/policy
and engine/fill-model revisions, date range, parameters, code version, and a
run fingerprint.
3. Write each run to a private staging directory, validate it, then atomically
publish decisions, fills, equity curve, metrics, and report with a manifest.
4. Add an `ops_jobs` catalog: submit, start, progress, cancellation, retry,
lock lease, terminal result, and bounded read-only concurrency. Serialize
SQLite catalog/ledger writes through one durable worker.
5. Replace the global log queue with per-job persisted events read by cursor;
SSE reconnects and fans out events without consuming another viewer's stream.

**Exit criteria:** parallel backtests never share state or artifacts; retrying
the same fingerprint returns the existing completed result or a safe retry;
disconnecting an SSE client does not stop a job.

## Phase 5 — Transactional ledger and paper execution

**Implementation status (2026-09-11):** a WAL SQLite append-only paper ledger
supports account versions, idempotency keys, atomic fill batches, and rebuilt
FIFO projections. It is not yet the legacy portfolio's authority.

**Outcome:** one source of truth for portfolio facts, auditable manual work,
and safe paper execution.

1. Create a single SQLite ledger namespace with accounts, cash entries, lots,
decision events, order intents, attempts, fills, capital events, manual
operations, reconciliation events, audit events, and projection checkpoints.
2. Implement command handlers in `execution_gateway`. Each handler validates
the expected aggregate revision and idempotency key, then records all state,
cash/lot, audit, and transition effects in one transaction.
3. Support the lifecycle `PROPOSED → APPROVED → DISPATCHING → SUBMITTED →
PARTIALLY_FILLED → FILLED`, with explicit failure/cancel/reconciling paths.
4. Route manual trades, capital events, corrections, and corporate actions
through these commands. Corrections are compensating events, never edits to
approved or submitted history.
5. Build projections from ledger facts and compare them against legacy
holdings/summary history. Cut over read views only after reconciliation passes.

**Exit criteria:** interruption and retry tests never duplicate exposure or
cash effects; a projection rebuild equals the stored dashboard view; paper
operations pass an end-to-end reconciliation drill.

## Phase 6 — Provider hardening and live-execution gate

**Implementation status (2026-09-11):** provider protocols and an explicitly
paper-only broker exist. Any `allow_live=True` submission is rejected; no
broker order API is called by this implementation.

**Outcome:** broker integration is recoverable, idempotent, and disabled by
default until signed off.

1. Introduce provider ports for historical bars, quotes, instruments, and
broker operations. Move credentials to the OS credential store or an explicit
local secret provider; redact provider payloads and secrets from logs.
2. Make token renewal an explicit CLI/job workflow, never an HTTP request that
opens a browser or waits for a callback.
3. Implement broker dispatch as a job: pre-flight reconciliation, intent tag,
broker ID persistence, sell-first/confirmed-cash/buy-third sequencing,
partial-fill recovery, and post-submit reconciliation.
4. Add a paper broker adapter first, then broker sandbox tests and failure
simulations: timeout after submit, duplicate callback, restart during dispatch,
partial fill, rejected order, and broker/local position mismatch.
5. Add an explicit operational go-live checklist and a feature flag requiring
manual operator enablement for real orders.

**Exit criteria:** every order attempt is traceable to intent and broker ID;
retry/restart cannot duplicate an order; paper reconciliation and failure drills
pass before production credentials can be used for dispatch.

## Phase 7 — Application cutover and legacy retirement

**Implementation status (2026-09-11):** the server is a backend-only
composition layer: legacy v1/UI routes and startup `create_all()` are not
registered, while health and authenticated v2 durable-job endpoints are
available. Local SQLite health and backup CLI utilities are implemented.

**Outcome:** Flask becomes an adapter/composition layer and old mutable paths
are removed only after verified migration.

1. Convert HTTP endpoints from synchronous workflows into job submission and
query endpoints; retain backward-compatible wrappers during a deprecation
window.
2. Add CLI commands for EOD ingestion, artifact publication, rank creation,
backtest submission, paper dispatch, reconciliation, backup, restore, and
projection rebuild.
3. Migrate legacy market/personal/backtest data with one-time import manifests,
row-count/checksum reconciliation, and reversible mapping records.
4. Remove legacy `ActionGenerator`/`ActionLifecycle`/`ActionProcessor`, shared
`backtest.db`, global SSE queue, and `create_all()` only after adapters point
solely at the new packages and parity is signed off.

**Exit criteria:** no route contains financial rules; import-boundary tests
pass; production data has a verified ledger/catalog import manifest; legacy
writes are disabled before their tables/files are archived.

## Phase 8 — Measured scale-out and operational maturity

**Implementation status (2026-09-11):** readiness/liveness endpoints and
SQLite backup primitives are implemented. PostgreSQL, Parquet/DuckDB, CI,
alerts, and multi-user RBAC remain evidence-driven future work.

**Outcome:** improve storage and deployment only when evidence justifies it.

1. Benchmark SQLite/catalog throughput and artifact reads. Adopt Parquet plus
read-only DuckDB only after snapshot-parity and atomic-publish tests pass.
2. Migrate catalog/ledger to PostgreSQL only for demonstrated concurrent-write,
remote/multi-user, restore, or operations requirements. Keep package contracts
and ports unchanged.
3. Add health/readiness checks, structured audit retention, backup scheduling,
restore drills, dependency/security scans, release gates, and operational
alerts.
4. Add RBAC only when deployment stops being local single-user; do not imply
multi-user safety before that decision.

**Exit criteria:** performance work meets documented benchmarks without losing
reproducibility; backup/restore drills succeed; every deployment is gated by
tests, migration checks, and a reversible release procedure.

## Suggested release gates

| Gate | Required evidence |
|---|---|
| Research parity | Golden-data comparison, manifest completeness, approved delta ledger |
| Ledger cutover | Transaction/retry tests, projection rebuild parity, backup/restore drill |
| Concurrent research | Parallel-run isolation, cancellation/retry test, event-stream fan-out test |
| Paper trading | Daily reconciliation for an agreed observation period, broker-failure simulations |
| Live execution | Explicit operator approval, go-live checklist, rollback/kill switch rehearsal |
| Legacy retirement | No legacy writes, migration reconciliation report, retained read-only archive |

## Immediate implementation order

Start with Phase 0, then build Phase 1 before changing research storage. The
highest-risk cutovers are ledger/execution and immutable market lineage; they
should not be combined in one release. A practical first implementation slice
is: contracts + tests, exact config update, migration/backup discipline, pure
portfolio engine with golden tests, then an in-memory backtest prototype.
