# Target Architecture: Extensible Modular Monolith

> **Status:** Proposed design — implementation has not started.  
> **Purpose:** Replace the current Flask/SQLite monolith with a modular, auditable research and execution system.  
> **Scope:** Architecture and migration plan only. It does not authorize runtime or production-code changes.

---

## 1. Executive decisions

The system is one repository and initially one deployable application. It uses focused packages rather than three oversized modules or prematurely distributed microservices.

1. `platform_kernel` remains deliberately small: contracts, IDs, versioning, manifests, ports, and domain errors only.
2. Reference data, market data, indicators, strategies, portfolio decisions, portfolio accounting, backtesting, execution, and application adapters are separate packages.
3. UI-managed research is declarative: it composes approved indicators, expressions, and policies. It never runs arbitrary Python, SQL, shell commands, network calls, or broker requests.
4. Indicator definitions, indicator configurations, strategy revisions, portfolio-policy revisions, snapshots, rankings, and backtest inputs are immutable once used.
5. A pure `PortfolioEngine` is the only decision/state-transition implementation used by live workflows and backtesting. This gives replay parity; the design does not claim unprovable “zero simulation drift.”
6. Backtests run in memory and publish isolated artifacts. They never use, clear, or share `backtest.db`.
7. SQLite is the supported initial local/single-user relational store. PostgreSQL is an explicit migration target when concurrent writers, remote/multi-user access, or operational backup requirements warrant a separately operated database service.
8. Immutable analytical datasets are stored separately from mutable ledger state. DuckDB is optional and read-only for analytics; it is never a system-of-record writer.
9. No requirement is silently “out of scope”: it must have a phase, be explicitly removed from product requirements, or block the relevant release.
10. This is a **local, single-user** deployment. Network-facing authentication and multi-user authorization are intentionally deferred; local correctness, credential handling, validation, and auditability are not deferred.
11. A named configuration update always targets that exact stable ID. A value used by research, a decision, or an execution attempt is frozen as a versioned revision; it is never edited in place.
12. SQLite has one explicit write-coordination policy: transactional ledger changes use one writer/job at a time, while read-only research may run concurrently. Reaching sustained concurrent-write needs is the trigger for PostgreSQL, not an invitation to share scratch databases.

---

## 2. Package topology and dependency rules

```text
application
  ├── execution_gateway
  ├── backtesting
  ├── portfolio_accounting
  ├── portfolio_engine
  ├── strategies
  ├── indicators
  ├── market_data
  └── reference_data
              │
              ▼
       platform_kernel
```

`application` is the composition root: dashboard, REST API, CLI, scheduled jobs, dependency wiring, authentication, and presentation. It contains no financial rules.

Dependencies point inward toward `platform_kernel`.

- `reference_data` does not import any domain package above it.
- `market_data` consumes reference-data contracts, but not indicators, strategies, portfolio, execution, or application code.
- `indicators` consumes market/reference contracts, but not strategy, portfolio, execution, or application code.
- `strategies` consumes feature, market, and reference contracts, but not portfolio, execution, or UI code.
- `portfolio_engine` consumes platform contracts and ranking/policy inputs, but has no storage, indicator, broker, or UI dependency.
- `portfolio_accounting` consumes portfolio and ledger contracts, but owns neither portfolio decisions nor broker integration.
- `backtesting` invokes strategies, portfolio decisions, and accounting; it owns no duplicate financial rule.
- `execution_gateway` invokes portfolio and accounting APIs, but does not calculate indicators or rankings.
- Only `application` wires concrete providers, repositories, and other adapters to ports.

Every package exports a small `api.py`; no other package may import an internal module. Import-boundary tests enforce this.

| Package | Owns | Must not own |
|---|---|---|
| `platform_kernel` | contracts, ports, manifests, IDs, versions, errors | Formulae, ORM, Flask, broker SDKs, filesystem code |
| `reference_data` | instruments/ISIN identity, aliases, token history, calendars, universes, corporate actions, fundamentals | OHLCV, indicators, portfolio decisions |
| `market_data` | source adapters, raw/normalized bars, benchmark and quote streams, availability checks | indicator formulae, scores, orders |
| `indicators` | definitions, dependencies, warm-up, feature calculation, indicator catalog | strategy weights, order behavior |
| `strategies` | eligibility, factors, percentiles, score/ranking rules, strategy catalog | indicator implementation, broker calls |
| `portfolio_engine` | sizing, stops, rebalance, pyramids, swaps, decision state machine | accounting persistence, broker details |
| `portfolio_accounting` | cash flows, valuation, FIFO journal, XIRR, risk/summary projections | trade selection or broker calls |
| `backtesting` | replay, fill model, metrics, reports, run catalog | duplicate portfolio/accounting logic |
| `execution_gateway` | ledger, approvals, manual operations, broker routing, reconciliation | strategy/indicator computation |
| `application` | API/UI/CLI/jobs, dependency injection, auth and presentation | domain logic |

---

## 3. Stable contracts, lineage, and quality

`platform_kernel` defines versioned contracts at all boundaries:

- `Instrument`, `InstrumentAlias`, and `InstrumentSnapshot`.
- `MarketBar`, `MarketSnapshot`, `BenchmarkSnapshot`, and `QuoteSnapshot`.
- `UniverseSnapshot`, `CorporateActionSnapshot`, and `FundamentalSnapshot`.
- `IndicatorRevision`, `IndicatorConfiguration`, and `FeatureSnapshotSet`.
- `StrategyRevision`, `PortfolioPolicyRevision`, `PercentileSnapshot`, `ScoreSnapshot`, and `RankingSnapshot`.
- `PortfolioState`, `DecisionEvent`, `OrderIntent`, and `ExecutionReport`.
- `BacktestRunManifest`, `JobManifest`, and `ArtifactManifest`.

Each manifest includes contract schema version, engine/implementation version, upstream IDs, creation time, content checksums, data-quality status, and output IDs. A result is not presented without its manifest.

### Data quality contract

Data is explicit about usability:

```text
COMPLETE | PARTIAL | STALE | MISSING | ADJUSTMENT_PENDING | SOURCE_FAILED
```

A strategy declares minimum data capabilities: for example, a benchmark-dependent strategy blocks without its benchmark; a live order requires complete, current inputs. A backtest allowed to use partial data is visibly marked as qualified.

### Invariants

- A position cannot sell more units than are held.
- A decision cannot allocate more than confirmed available cash.
- The same state, policy, and snapshots produce the same portfolio transition.
- A strategy references compatible, versioned features only.
- Editing an indicator, strategy, or policy cannot change historical outputs.
- An interrupted order workflow can be reconstructed from ledger events and broker reconciliation.
- A request cannot move an action between lifecycle states unless the transition, field set, and invariant checks are valid for its current state.
- A configuration update cannot affect a configuration other than the stable ID named by the command.
- A published artifact is complete with a verified manifest, or is absent; partially written artifacts are never discoverable.

---

## 4. Versioned research model

### 4.1 Indicators

An indicator is a versioned definition with declared inputs, parameter schema, output schema, dependencies, warm-up requirement, and implementation hash.

```text
indicator_id: ema
indicator_revision: uuid
semantic_version: 1.0.0
inputs: [close]
parameters: { length: 50 }
warmup_bars: 50
outputs: [ema_50]
```

The UI may create an `IndicatorConfiguration` by choosing an approved definition, parameters, and output alias. A changed formula, input semantics, or output semantics creates a new indicator revision. It never overwrites a prior feature result. New mathematical primitives or external sources require reviewed code and tests in `indicators`.

### 4.2 Strategies and policies

A strategy has a stable `strategy_id` and immutable `strategy_revision_id`. A revision stores its semantic version, parent revision, full declarative definition, definition hash, required feature configurations, eligibility policy, and lifecycle status.

```text
StrategyRevision
  strategy_id: momentum
  strategy_revision_id: UUID
  semantic_version: 1.2.0
  parent_revision_id: UUID | null
  definition_hash: SHA-256
  portfolio_policy_revision_id: UUID
```

Changing factor weights, thresholds, eligibility, feature configuration, stop rules, sizing rules, or rebalancing behavior creates a new strategy and/or portfolio-policy revision. It never edits the active or historical revision.

The UI supports safe composition of approved indicators, whitelisted expressions, weights, and approved policies. Server validation rejects circular dependencies, unknown features, invalid types/weights, insufficient warm-up, and impossible risk limits.

Configuration commands use a typed, explicit patch contract rather than an ORM object update.  Each field has a domain constraint (for example: positive capital and ATR multiplier, non-negative risk, `max_positions >= 1`, and concentration in `(0, 1]`).  A command carries `config_id`, `expected_revision`, and only allowed fields.  The repository updates `WHERE config_id = ? AND revision = ?`; zero rows changed is a conflict, never a fallback to an arbitrary first configuration.  The result is a new immutable `PortfolioPolicyRevision` and an audit event.

```text
DRAFT → VALIDATED → BACKTESTED → PAPER → APPROVED → ACTIVE → RETIRED
```

Only an approved revision can create a live `OrderIntent`.

### 4.3 Immutable percentiles, scores, and rankings

Percentiles, scores, and rankings are separate derived artifacts. A ranking is never keyed only by `strategy_id + date`.

```text
PercentileSnapshot = strategy_revision + feature_snapshot_set + universe_snapshot + as_of_date
ScoreSnapshot      = strategy_revision + percentile_snapshot + as_of_date
RankingSnapshot    = strategy_revision + score_snapshot + universe_snapshot + as_of_date
```

For example, the following coexist and are both auditable:

```text
momentum@1.0.0, 2025-01-03 → RankingSnapshot A
momentum@1.1.0, 2025-01-03 → RankingSnapshot B
```

Ranking members include instrument ID, eligibility status/reason, factor values, percentile values, score, rank, and explanation. A strategy change publishes a new snapshot; it never rewrites the old ranking.

---

## 5. Storage architecture and database types

### 5.1 Storage classes

```text
Immutable analytical artifacts              Mutable relational state
reference → market → features → research   catalog/control + live ledger + jobs
             │                                              │
             └────────── manifests and stable IDs ──────────┘
```

| Data class | Initial storage | Future path | Purpose |
|---|---|---|---|
| Catalog/control metadata | SQLite, WAL | PostgreSQL | definitions, versions, manifests, artifacts, jobs |
| Operational ledger | SQLite, WAL | PostgreSQL | cash, lots, decisions, orders, fills, audit |
| Immutable analytical artifacts | versioned files | same | reference, bars, features, research, backtest output |
| Analytical query engine | Python/pandas initially | read-only DuckDB | scans, research, ranking performance |

PostgreSQL requires a separately operated server: local installation/Docker for development, or a managed/self-hosted service for deployment. It is not required in the first local/single-user phases. The relational-port interfaces and migrations must keep a later SQLite-to-PostgreSQL move feasible.

### 5.2 Logical relational stores

Initially the local database contains three logical namespaces (implemented by table prefixes if SQLite lacks schemas):

```text
catalog_*  definitions, revisions, snapshots, artifacts, lineage, quality
ledger_*   accounts, cash events, lots, decisions, orders, fills, reconciliation
ops_*      jobs, attempts, locks, progress events, notifications, audit records
```

When PostgreSQL is adopted, these become the `catalog`, `ledger`, and `ops` schemas in one database. This permits transactions across catalog/job state when required without splitting the system into multiple operational databases.

### 5.3 Ground-source hierarchy

The immutable store is layered; derived research never replaces source data.

```text
1. Reference ground truth
   instruments, ISIN/aliases, exchange/token history, calendars,
   corporate actions, point-in-time universes, fundamentals

2. Market ground truth
   raw provider bars and quotes → normalized/adjusted market bars → benchmarks

3. Derived research products
   feature sets → percentile sets → score sets → ranking snapshots

4. Consumer outputs
   backtests, paper-trading runs, live-decision manifests
```

Suggested artifact layout:

```text
data/
  reference/{instruments,universes,corporate_actions,fundamentals}/<snapshot_id>/
  market/{raw/<provider>,normalized,benchmarks}/<snapshot_id>/
  features/<feature_snapshot_set_id>/
  research/{percentiles,scores,rankings}/<snapshot_id>/
  runs/{backtests,paper}/<run_id>/
```

Each directory contains a manifest, schema version, checksums, quality result, upstream IDs, and data file(s). The current first implementation may use SQLite-backed exports; Parquet is adopted when its performance benefits are measured and parity-tested.

### 5.4 Publish, correction, and invalidation rules

```text
write staging artifact → validate schema/count/quality/checksum
→ atomically publish artifact → commit catalog artifact/lineage record
```

Data corrections do not overwrite published artifacts. A corrected market or reference snapshot supersedes the earlier one; downstream artifacts are marked `VALID`, `SUPERSEDED`, `QUALIFIED`, or `REVOKED` according to lineage. Historical rankings/backtests preserve their original inputs and remain reproducible.

Artifact publication is crash-safe: write to a run-private staging directory, fsync/checksum and validate it, atomically rename it into the immutable namespace, then commit the catalog record in the same recoverable publish protocol.  Startup recovery removes or quarantines unreferenced staging directories and marks catalog records with missing artifacts as failed rather than serving partial files.  Retention deletes catalog references and artifacts through the same job, with tombstone/audit records and retryable cleanup.

An `InvalidationPlan` records the downstream effect of a correction:

```text
market/reference correction
  → features → percentiles → scores → rankings
  → affected backtest/paper/live-decision qualification or rerun requirement
```

---

## 6. Portfolio, accounting, backtesting, and execution

### 6.1 Portfolio engine

`portfolio_engine` owns the sole state machine for selection and state transitions. It accepts a `PortfolioState`, ranking/market snapshots, and a policy, then returns `DecisionEvent` values plus next state.

It owns sizing and cash constraints, stop and trailing-stop rules, sell/buy/pyramid/swap order, mid-week vacancy policy, corporate-action position normalization, and microstructure eligibility.

```text
if open <= hard_stop: fill at open, HARD_STOP_GAP_OPEN
elif low <= hard_stop: fill at hard_stop, HARD_STOP_INTRADAY
else: no hard-stop fill
```

### 6.2 Accounting

`portfolio_accounting` computes portfolio economics from ledger facts:

- capital infusions, withdrawals, and realized gains;
- cash ledger entries and confirmed fill-derived lots;
- valuation, risk, realized/unrealized P&L, summaries;
- FIFO trade journal and XIRR.

Weekly summaries are projections, not the financial source of truth.

### 6.3 Backtests and research runs

`backtesting` is an in-memory driver of strategies, `PortfolioEngine`, and accounting. A run fingerprint includes strategy revision, portfolio-policy revision, parameters, date range, all input snapshot IDs, and engine/fill-model versions.

```text
data/runs/backtests/<run_id>/
  manifest.json
  decisions.parquet
  fills.parquet
  equity_curve.parquet
  metrics.json
  report.html
```

The run catalog supports labels/tags, listing, comparison, retention/deletion policy, cancellation, bounded parallelism, and safe retry. No run writes production holdings or a shared scratch database.

### 6.4 Execution and manual operations

`execution_gateway` owns live ledger persistence, manual operations, broker translation, approval, and reconciliation. Every action has an origin:

```text
STRATEGY | MANUAL | RECONCILIATION | CORPORATE_ACTION
```

Manual buys/sells, capital events, and reconciliation adjustments create the same auditable decisions/order intents as strategy actions; they cannot bypass accounting or risk validation.

```text
PROPOSED → APPROVED → DISPATCHING → SUBMITTED → PARTIALLY_FILLED → FILLED
                                      └────────→ FAILED / CANCELLED / RECONCILING
```

The ledger records accounts, capital events, cash entries, lots, decision events, order intents, attempts, broker IDs, fills, manual operations, reconciliation events, and audit events. Before placement, it reconciles intent with the broker; tags assist reconciliation but are not the only idempotency mechanism.

Authentication, dispatch, broker recovery, and long-running work execute as jobs. Live dispatch is sell-first, confirmed-cash-second, buy-third.

All ledger-affecting commands execute inside one database transaction owned by `execution_gateway`.  Repositories do not commit internally.  A transaction either records the complete state transition, cash/lot effects, order intent, and audit event, or records none of them.  Commands carry an idempotency key and expected aggregate version; retries return the prior result, and stale/concurrent attempts fail as conflicts.  Summaries and dashboards are projections rebuilt from ledger facts, never independently authoritative rows.

Manual actions are commands with strict schemas: positive integer units, positive finite prices, supported enums, known instrument identity, and a permitted state transition.  They cannot edit an approved decision or a submitted order; correction is a new compensating/reconciliation event linked to the original record.

---

## 7. Providers, jobs, and application adapters

Provider ports prevent a single source from leaking across the design:

```text
HistoricalBarsProvider     InstrumentProvider
BenchmarkProvider          FundamentalsProvider
LiveQuoteProvider          QuoteStream
Broker                     ArtifactStore
CatalogRepository          LedgerRepository
```

Kite, YFinance, NSE/BSE files, SQLite/PostgreSQL, filesystem/Parquet, REST, and SSE are adapters. Live quote streaming is a `market_data` capability consumed by execution/dashboard code, not owned by the broker ledger.

`application` owns job submission/status/cancellation, structured progress events, SSE/Web UI presentation, CLI commands, authorization, and audit presentation. HTTP requests create or inspect jobs; they do not synchronously authenticate, import history, run a full pipeline, backtest, or dispatch orders.

### 7.1 Local runtime guardrails

Local-only does not mean shared mutable globals.  `ops_jobs` records the request fingerprint, owner, attempt, cancellation state, lock lease, and terminal outcome.  A single durable write worker serializes SQLite ledger/catalog mutations; read-only work has bounded worker capacity.  Backtests receive a private in-memory state and a unique run directory, so no run can clear, reuse, or observe another run's working state.

SSE is a presentation adapter, not a global `Queue`.  Each job emits structured progress to its own persisted event stream; each connected client reads that stream by cursor.  This provides reconnects, fan-out (every subscriber sees the same events), bounded retention, and prevents one viewer from consuming another viewer's messages.  Sensitive provider errors are redacted before persistence or display.

Broker credentials are held outside the repository in the operating system's credential store (or an explicitly configured local secret provider).  Token renewal is an explicit local CLI/job workflow; a web request never opens a browser, starts a callback listener, or blocks while waiting for a human login.  The provider port receives a short-lived credential at call time and logs neither credentials nor full provider payloads.

---

## 8. Risk-first migration phases

Each phase is additive. It preserves existing behavior until replacement parity and acceptance criteria are met.

### Phase 0 — Design, ownership, validation, and storage baseline

Define package ownership, dependency rules, public APIs, contracts, versioning, local SQLite namespaces, manifests, provider ports, command validation, SQLite writer policy, credential-provider boundary, and test plan. Map every current source capability to a target owner. Replace `create_all()` startup schema mutation with reviewed, versioned migrations and a verified backup/restore path.

**Exit:** agreed storage/lineage policy, import rules, typed command contracts, migration policy, and no unowned current feature.

### Phase 1 — Financial correctness and replay parity

Create pure portfolio decisions and accounting contracts; verify stops, gaps, sizing, swaps, pyramids, manual trades, cash events, FIFO, and valuation with golden scenarios. Build in-memory backtests; retire shared backtest state. Make the ledger transition plus projections transactional and idempotent.

**Exit:** repeatable simulations with no shared database writes, idempotent ledger commands, and passing state-transition tests.

### Phase 2 — Reference/market data lineage and invalidation

Introduce instrument/token history, calendar, corporate-action, universe, benchmark, fundamental, raw/normalized market snapshots, quality assessment, and invalidation plans.

**Exit:** corrections create a superseding lineage rather than silently altering research inputs.

### Phase 3 — Versioned indicators, strategies, and rankings

Add indicator revisions/configurations, strategy/policy revisions, immutable feature/percentile/score/ranking snapshots, validation, and UI research drafts.

**Exit:** a weight change creates a new strategy revision and separate historical ranking for the same date; old rankings remain auditable.

### Phase 4 — Isolated concurrent research operations

Add run catalog, manifests, crash-safe artifact publication, bounded parallel jobs, cancellation, run comparisons, per-job event streams, and paper-trading promotion.

**Exit:** concurrent backtests cannot overwrite one another and retries are idempotent.

### Phase 5 — Ledger, manual workflow, and broker safety

Consolidate live state into the event ledger. Add manual-operation origins, approval, reconciliation, interruption recovery, and broker failure simulations.

**Exit:** no duplicate exposure across retry/restart paths; manual operations remain auditable and policy-checked.

### Phase 6 — Package extraction and application simplification

Extract proven components into packages, remove flat imports/global path mutation, and convert UI/API/CLI to adapters and composition only.

**Exit:** import-boundary tests pass and no business logic is duplicated between entry points.

### Phase 7 — Artifact performance and relational scale-out

Measure workloads. Adopt Parquet/atomic publishing/read-only DuckDB only after ranking/backtest parity. Migrate SQLite catalog/ledger to PostgreSQL only when required by measured concurrent-write, remote/multi-user, backup, or service-operation needs.

**Exit:** demonstrated performance or operations benefit with verified parity and restore procedure.

### Phase 8 — Operational maturity

Add RBAC if the local-only deployment model changes, monitoring, backup/restore drills, health checks, structured auditing, alerts, release controls, and advanced broker/regulatory models.

**Exit:** normal failure, recovery, backup, and approval workflows are documented and exercised.

---

## 9. Design review checklist

Before accepting a proposal, verify:

- Does it have one owner package and public API?
- Does it preserve dependency direction and provider ports?
- Is a new strategy/indicator an additive, versioned change?
- Does a ranking include a strategy revision and immutable upstream snapshot IDs?
- Does it preserve historical manifests and backtest reproducibility?
- Does it separate source/reference, market, features, and research artifacts?
- Does it specify validation, retry, error, and recovery behavior for state changes?
- Does it include proportional unit, contract, integration, replay, and migration-parity tests?
- Does every named update use that exact stable ID plus optimistic version check, rather than a broad or positional query?
- Can an interrupted command leave neither partial ledger state nor a visible partial artifact?
- Are concurrent SQLite writes serialized as jobs, and are all backtest workspaces private?
- Are lifecycle transitions, positive monetary/quantity constraints, and idempotency explicitly tested?
- Does token renewal avoid browser/callback work inside an HTTP request, and are logs redacted?

---

This architecture favors clear ownership, durable auditability, and safe local operation first, while preserving a measured path to PostgreSQL and analytical storage optimization.
