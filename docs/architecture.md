# Architecture

## System context

The application is a local modular monolith for four related concerns:

1. reference and market-data ingestion;
2. indicator calculation, strategy scoring, and ranking;
3. isolated historical backtesting; and
4. accounting for one or more real portfolios.

The default deployment is one Waitress process bound to loopback, one
background worker thread, and one SQLite database. Kite is the authoritative
provider for instruments, historical bars, quotes, and optional broker
execution. YFinance is used only for the current market-cap enrichment needed
to create and extend the investable universe.

## Runtime composition

`run.py` is the web entry point. It resolves configuration, creates
`ApplicationServices`, registers Flask blueprints, starts the background job
worker, and starts the market-hours index poller when Kite market credentials
are available.

`src/application/composition.py` is the dependency-composition root. It creates
all repositories and services against `instance/system.db`, seeds strategy
definitions, and maps durable job kinds to handlers. Domain packages do not
construct Flask, Kite, or SQLite application services themselves.

```text
Browser / API client
        |
        v
Flask blueprints in src/application/*_web.py
        |
        +---- synchronous reads and small commands
        |
        +---- durable JobStore submissions
                       |
                       v
                 JobWorker handlers
                       |
          +------------+-------------+
          |            |             |
          v            v             v
   repositories   domain engines   providers
          |            |             |
          +------------+-------------+
                       |
                       v
                instance/system.db
```

## Package responsibilities

| Package | Responsibility |
|---|---|
| `src/application` | Composition, SQLite repositories, jobs, workflows, providers, and HTTP adapters |
| `src/platform_kernel` | Shared value types, errors, contracts, and immutable artifact storage |
| `src/market_data` | Normalized market-bar contracts and validation |
| `src/reference_data` | Instrument identity and reference-data contracts |
| `src/indicators` | Approved Pandas TA catalogue and custom feature implementations |
| `src/strategies` | Strategy-domain scoring contracts |
| `src/backtesting` | Pure replay and performance calculations |
| `src/portfolio_accounting` | Fills, FIFO lots, cash, and portfolio projections |
| `src/portfolio_engine` | Candidate selection and portfolio decision policy |
| `src/execution_gateway` | Real ledger persistence and broker execution/reconciliation |

The application layer may depend on these packages. Lower-level domain
packages must not import `src.application`; the import-boundary test protects
that direction.

## Persistence architecture

All active runtime state is stored in one SQLite file. It contains:

- normalized relational projections used for queries;
- durable jobs and their event histories;
- immutable compressed JSON artifact payloads;
- artifact catalogue, lineage, publication, and invalidation records;
- strategy definitions and active immutable revisions;
- market bars, coverage windows, research scores, and rankings;
- the append-only portfolio ledger and broker execution records.

Each store owns migrations in a namespace. `migrate_sqlite()` records applied
versions in `system_schema_migrations`. Schema creation occurs when services
are composed, not through an ORM-wide `create_all` operation.

SQLite WAL and SHM files are transient companions while the application is
running. Use SQLite backup operations before sharing the database.

## Durable work

Long operations are submitted to `JobStore` with a unique fingerprint. A job
has a bounded retry policy, a lease owner, a claim token, progress events,
cancellation state, and an optional result. The worker claims one job at a
time per worker loop and invokes only handlers registered in the composition
root. Bulk research claims are additionally serialized in `JobStore`, so a
second process cannot run another research range concurrently against the same
database.

Research pipelines coordinate ordinary durable jobs. Without data
orchestration they submit one `research.rebuild-range` job immediately. With
data orchestration they wait for reference, market refresh, reconciliation,
and spawned bar jobs before submitting that same bulk range job. The handler
loads history once and reports indicator, percentile, score, and ranking
progress through durable job events.

## Immutable artifacts and projections

Large or lineage-sensitive outputs are published as compressed JSON in
`artifact_payloads`. `ArtifactPublisher` coordinates payload publication with
the relational catalogue. Derived relational tables such as daily scores and
weekly rankings are query projections whose rows reference their artifact and
strategy revision.

Publication follows an immutable identity rule: the same artifact ID must
represent the same payload. Recovery can complete an interrupted catalogue
projection, quarantine corrupt content, and invalidate downstream lineage.

## External boundaries

### Kite market-data profile

The shared market profile reads instruments, historical bars, and quotes. Its
OAuth token is separate from the portfolio profile.

### Kite portfolio profile

The portfolio profile is used by `KiteExecutionGateway`. Live order dispatch
is disabled unless explicitly enabled. The gateway also has a runtime arm/
disarm control.

### YFinance

YFinance is not a historical-bar fallback. It enriches the deduplicated Kite
instrument set with current market capitalisation for the fixed-universe
build. Expected provider failures make a symbol unresolved; unexpected code
errors fail the job and preserve the previous active universe.

## Trust boundaries and safety

- The application has no local authentication layer and must remain bound to
  loopback unless it is deployed behind a separately secured boundary.
- Kite OAuth is the only authentication flow.
- Market-data and portfolio Kite credentials never fall back to each other.
- Generated strategy proposals are advisory records, not transactions.
- Only explicitly confirmed manual transactions or broker-confirmed fills may
  change the real ledger.
- Backtest state is isolated from the ledger.
- A partial universe build is never active.
- Holdings remain in the market refresh set even when they leave the screening
  universe or are on a price circuit.

## Web surfaces

Blueprints expose `/api/v2` resources for operations, reference data, market
data, research, pipelines, indicators, strategy revisions, portfolio,
execution, actions, and backtests. `/app` serves the local UI, while
`/health/live` tests process liveness and `/health/ready` tests local database
readiness. Provider connectivity is deliberately excluded from health checks.
