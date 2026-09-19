# Implementation guide

## Repository map

```text
run.py                    Flask/Waitress entry point
src/application/          composition, web adapters, repositories, jobs
src/platform_kernel/      shared contracts and artifact storage
src/market_data/          normalized market-bar domain
src/reference_data/       instrument identity domain
src/indicators/           Pandas TA adapter and custom calculations
src/strategies/           strategy scoring contracts
src/backtesting/          replay and statistics engine
src/portfolio_accounting/ fills and FIFO projection
src/portfolio_engine/     portfolio decision rules
src/execution_gateway/    real ledger and Kite order boundary
strategies/               seed YAML strategy definitions
templates/, static/       local browser UI
scripts/                  operational and smoke utilities
tests/                    unit, integration, recovery, and regression tests
.tours/                   interactive source walkthroughs
docs/                     maintained documentation
```

## Application startup

1. `run.create_app()` loads `RuntimeConfig` and resolves the data directory and
   Kite token paths.
2. `ApplicationServices.create()` creates stores against `system.db`.
3. Each store applies its namespaced migrations.
4. Strategy YAML files are validated, inserted as immutable revisions, and
   activated only when no suitable active revision exists.
5. The job-handler registry is constructed.
6. Flask blueprints receive explicit service dependencies.
7. `main()` starts the durable worker and, when configured, the index poller.

Tests should normally call `create_app(TestConfig)` or
`ApplicationServices.create(tmp_path)` so every test gets an isolated database.

## Adding an HTTP capability

1. Put business behavior on an application service or domain package, not in
   the blueprint.
2. Add the route to the area-specific `*_web.py` module.
3. Validate JSON shape before calling the service; domain validation failures
   should become a clear 4xx response.
4. Register a new blueprint only when no existing area owns the route.
5. Add route tests for success, malformed input, missing state, and idempotent
   retries where applicable.

No route should add a local authentication token. The current application is
loopback-only; network deployment security is a separate pending capability.

## Adding a durable job

Use a job when work is provider-bound, potentially long-running, retryable, or
has dependent stages.

1. Implement a handler accepting `payload` and optionally a
   `JobExecutionContext`.
2. Validate the complete payload at the handler boundary.
3. Call `context.checkpoint()` during bounded batches.
4. Register the kind in `ApplicationServices.create()`.
5. Submit with a deterministic fingerprint that includes all material inputs.
6. Return a small JSON-serializable result containing IDs and counts, not a
   large data payload.
7. Test duplicate submission, cancellation, lease expiry, retry, and failure.

Do not dynamically import a job handler from user input. The composition map
is the approved execution allowlist.

## Adding or changing SQLite state

Every table has one owning store. Add a monotonically increasing migration to
that store's `migrate_sqlite()` call. Migrations must be deterministic and
safe to run once on an existing database.

Guidelines:

- use ISO-8601 text for dates and timezone-aware timestamps;
- store money and quantities without binary floating-point loss;
- enforce natural idempotency with unique keys;
- wrap related projection changes in `BEGIN IMMEDIATE`;
- do not delete immutable historical records to update a projection;
- add indexes for actual lookup paths;
- add a migration test and a repository behavior test.

The application does not use SQLAlchemy metadata or standalone migration files
for current stores. The `migrations/` directory is not the active migration
mechanism.

## Publishing derived data

Use `ArtifactPublisher.publish_json()` when an output needs lineage,
immutability, checksum verification, or later reproduction. Build a stable
artifact ID from normalized inputs, include all upstream artifact/snapshot IDs,
and select the appropriate quality status.

If query performance needs relational rows, publish the artifact first and
then write a projection that references its ID. Provide a recovery path for a
crash between those operations. Never mutate the artifact payload to make a
projection match.

## Provider integrations

Provider SDK calls belong behind application providers or gateways. Normalize
their output immediately and convert expected provider errors into
`DomainValidationError`. Do not catch every `Exception` at a per-symbol level:
that can hide a coding defect and publish incomplete state.

Kite market and portfolio profiles are separate. New code must select the
correct profile explicitly and must not fall back between them.

## Testing strategy

The suite is organized by behavior rather than mirroring every source file.
Important categories are:

- pure domain tests for market, strategy, portfolio, and backtest rules;
- repository and SQLite migration tests;
- web contract tests;
- durable job lease/retry/recovery tests;
- artifact checksum and lineage tests;
- strategy parity and no-look-ahead regressions;
- provider adapter tests using fakes;
- smoke scripts for isolated end-to-end flows.

Run:

```powershell
poetry run python -m pytest -q
poetry run ruff check src tests scripts run.py
poetry run python -m compileall -q src tests scripts run.py
```

Mypy is configured but does not yet pass; see [pending items](pending-items.md).

## Change checklist

- Is the behavior owned by the correct module?
- Is external input validated once at the boundary?
- Is the operation idempotent under retry?
- Does it preserve point-in-time data and lineage?
- Could an interrupted write expose partial active state?
- Could it write a real portfolio fill without confirmed execution?
- Does a new table have an owned migration and test?
- Are the relevant guide and CodeTour still accurate?
