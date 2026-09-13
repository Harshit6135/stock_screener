# Current state

## Scope and versioning

This document describes the current modular backend implementation referred to
in the project as v4. The package metadata currently declares `3.0.0`; that
version-label mismatch should be resolved before a release, but it does not
change the code inventory below.

The previous v3 implementation is retained in
[the v3 archive](../archive/v3/Current%20state.md). It described a Flask-Smorest,
Flask-SQLAlchemy, dashboard, three-database application with v1 routes. Those
modules and routes are not part of the current source tree.

## What exists now

The current system is a Python 3.13 modular monolith. Flask and Waitress are
thin local-operation adapters; framework-independent domain packages contain
the research, portfolio, accounting, reference-data, backtesting, and ledger
contracts.

| Area | Current implementation |
|---|---|
| Runtime | `run.py` creates a loopback-by-default Flask app with `/health/live`, `/health/ready`, and the v2 operations blueprint. |
| Durable state | One `instance/system.db` SQLite database with namespaced migrations for catalog, operations jobs, and ledger data. Connections are transaction-scoped and deterministically closed. |
| Immutable artifacts | `platform_kernel.ArtifactStore` publishes staged, checksummed JSON payloads and manifests; `ArtifactCatalog` records lineage, publication states, invalidation, and tombstones. |
| Market and reference data | Typed normalized bars (with optional reported traded value), raw-provider evidence, point-in-time aliases, instruments, calendars, corporate actions, fundamentals, and a versioned liquidity-universe policy. |
| Research | Versioned indicator/configuration and strategy/policy contracts; separate percentile, score, and ranking snapshots with immutable inputs and tie-safe ranking. |
| Portfolio and accounting | A pure decision engine with stop, score-exit, swap, pyramid, fee, and slippage handling; FIFO accounting with currencies, fees, and execution times. |
| Backtesting | Validated run/fill-model manifests, shared execution assumptions, initial-equity-aware metrics, and cataloged run publication. |
| Kite authorization | Local daily authorization page, protected start endpoint, callback exchange, and atomic access-token refresh are implemented; configure the Kite redirect URL before use. |
| Execution | An append-only SQLite ledger with payload-bound idempotency and a paper broker that writes order-lifecycle and fill events. Live submission is disabled. |
| Jobs and operations | Leased, idempotent, cancellable jobs with claim tokens, retries, events, a local worker, read-only readiness checks, and verified SQLite backup/restore. |

## Public operation surface

Mutating routes require `SCREENER_OPERATOR_TOKEN` and the
`X-Operator-Token` request header.

| Endpoint or command | Purpose |
|---|---|
| `GET /health/live` | Process liveness. |
| `GET /health/ready` | Verifies the required SQLite migration namespaces. |
| `POST /api/v2/operations/jobs` | Submit an allowed durable operation job. |
| `GET /api/v2/operations/jobs/<id>` | Read job status and result. |
| `GET /api/v2/operations/jobs/<id>/events?after=<cursor>` | Read durable job events. |
| `POST /api/v2/operations/jobs/<id>/cancel` | Request cancellation. |
| `GET /api/v2/reference/liquidity-universes/<artifact-id>` | Read a checksum-verified, published liquidity-universe artifact. |
| `screener-ops work-once instance` | Claim and execute one queued job. |
| `screener-ops backup-sqlite <source> <destination>` | Create a verified SQLite backup without overwriting a destination. |
| `screener-ops restore-sqlite <backup> <destination>` | Restore a backup only to a new destination. |

The currently registered worker kinds are `system.echo`, `artifacts.recover`,
and `research.build-liquidity-universe`. The new liquidity job uses a
versioned turnover policy, rejects new equity entries with zero-volume, missing
or flat-OHLC completed bars, and records every exclusion reason. It does not
yet ingest exchange/Kite data itself; its JSON command is an integration seam
for that next phase. There is no v3 pipeline/dashboard compatibility endpoint.

## v3-to-v4 comparison

| v3 document claim | Current implementation | Status |
|---|---|---|
| Flask-Smorest OpenAPI and v1 blueprints serve screening, portfolio, and backtest routes. | Only a small Flask v2 operations API and health endpoints are registered. | Retired; no compatibility layer. |
| Flask-SQLAlchemy manages `market_data.db`, `personal.db`, and `backtest.db`. | Namespaced private SQLite stores share `system.db`; immutable artifacts live beneath `instance/artifacts`. | Replaced. |
| Mutable service/repository pipeline calculates indicators, scores, rankings, and actions. | Typed revisions and immutable artifacts provide domain seams, but only limited indicators and worker kinds are currently composed. | Partially rebuilt. |
| Dashboard, Swagger UI, SSE logging, and browser workflows are available. | No dashboard, Swagger UI, SSE stream, browser login, or live broker workflow is exposed. | Retired. |
| Backtests mirror mutable live tables and report v3 metrics. | A pure in-memory runner applies recorded fill assumptions and publishes cataloged results. | Replaced; parity is not claimed. |
| Paper actions and investment tables are authoritative. | An append-only ledger and paper broker provide the new authority. | Replaced; reconciliation remains a release gate. |

## Validation and release posture

Local Python 3.13 validation currently passes: 42 tests, 87% statement
coverage with an 85% threshold, Ruff formatting and linting, mypy, Bandit,
compile checks, dependency validation, Poetry lock validation, and wheel/sdist
build.

This is not yet a release-ready replacement for an existing v3 deployment.
The remaining gates are legacy-data migration and rollback, full research
pipeline/worker composition, provider calendar and adjustment policies,
broker reconciliation, and observed hosted CI plus production restore drills.
See the [gap review](Design%20and%20implementation%20gap%20review.md) for the
evidence and detailed status.
