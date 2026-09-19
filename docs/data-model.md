# Data model

## Storage conventions

The active database is `instance/system.db`. SQLite foreign keys are enabled by
the shared connection helper. Dates are ISO `YYYY-MM-DD`; timestamps are
timezone-aware ISO strings. JSON is stored only where the payload is naturally
variable or immutable. Monetary domain values are serialized as decimal text.

`system_schema_migrations` records `(namespace, version)` for every store-owned
migration. The table list below is grouped by owner rather than alphabetically.

## Artifact catalogue and payloads

| Table | Role |
|---|---|
| `artifact_payloads` | Compressed immutable JSON payload, manifest metadata, checksum, and publication state |
| `catalog_artifacts` | Queryable artifact identity, category, quality, checksum, and status |
| `catalog_lineage` | Directed upstream-to-downstream artifact relationships |
| `catalog_publications` | Publication state used to recover interrupted two-part writes |
| `catalog_invalidations` | Reasons and timestamps for invalidated artifacts |
| `catalog_tombstones` | Durable record that an artifact identity was removed or superseded |

An artifact ID is immutable. `ArtifactPublisher` first establishes publication
state, writes the payload, and completes catalogue projection. Recovery checks
checksums and reconciles any interrupted state. Relational rows reference
artifact IDs instead of copying large evidence payloads.

## Durable operations

| Table | Role |
|---|---|
| `ops_jobs` | Fingerprinted command, payload checksum, state, attempts, lease, cancellation, result, and last error |
| `ops_job_events` | Append-only state and progress history for a job |

The fingerprint is unique. Repeating the same submission returns the existing
job. Running work has a lease owner and claim token so a stale worker cannot
complete another worker's claim. Expired work can be requeued within its retry
limit.

## Instrument and market data

| Table | Key | Role |
|---|---|---|
| `reference_instruments` | `instrument_id` | Current normalized identity: ISIN, symbol, exchange, provider token, observation date |
| `reference_token_observations` | instrument/token/date | History of Kite token assignments |
| `universe_membership` | `isin` | Fixed investable members and membership provenance |
| `universe_build_state` | singleton row | Completion metadata that activates membership |
| `market_bars` | instrument/date | Normalized daily OHLCV and source snapshot |
| `market_fetch_coverage` | instrument/start/end/provider | Successfully requested provider ranges, including zero-bar ranges |
| `market_index_quotes` | index name | Latest index quote and source snapshot |
| `market_indicators` | strategy revision/instrument/date | Revision-aware feature cache and source artifact |

`active_universe_members()` returns no rows unless the build-state member count
exactly matches membership. `replace_universe_members()` replaces both in one
transaction. Raw rows from an interrupted historical build therefore remain
inactive.

Coverage is based on the union of `market_fetch_coverage` ranges, not inferred
from minimum and maximum bar dates. This prevents internal gaps from being
mistaken for full coverage and prevents repeated requests for valid pre-IPO
empty periods.

## Strategy definitions

| Table | Role |
|---|---|
| `strategy_definitions` | Stable strategy identity, display name, and description |
| `strategy_revisions` | Immutable source YAML, canonical JSON, semantic version, definition hash, lifecycle status, and timestamps |

The canonical JSON hash deterministically creates the revision identity.
Statuses are `DRAFT`, `VALIDATED`, `READY`, `ACTIVE`, and `RETIRED`, although a
YAML import currently enters as `VALIDATED`. Activating one revision retires
the previous active revision for that strategy.

Research and backtest rows always identify the active revision used for their
calculation.

## Research projections

| Table | Key | Role |
|---|---|---|
| `research_daily_scores` | strategy revision/date/instrument | Daily factor payload, final score, and artifact identity |
| `research_weekly_rankings` | strategy revision/week/instrument | Weekly score, deterministic rank, symbol, and artifact identity |
| `research_pipelines` | `pipeline_id` | Fingerprinted research request, strategies, and date range |
| `research_pipeline_stages` | pipeline/stage | Child job assigned to each pipeline stage |

Daily calculations first publish strategy-specific feature/score artifacts and
then replace the projection for the same strategy revision and date. Weekly
rankings aggregate available daily scores and use deterministic score-desc,
symbol-asc ordering.

## Backtests

| Table | Role |
|---|---|
| `backtest_runs` | Run identity, strategy/revision, date range, parameter fingerprint, artifact ID, and creation timestamp |

The full report is an immutable artifact. It contains the manifest, total and
annualized metrics, annual returns, risk ratios, drawdown, fill/order history,
and equity curve. Simulated fills are not ledger events.

## Portfolio ledger

| Table | Role |
|---|---|
| `ledger_accounts` | Account identity, opening cash, and currency |
| `ledger_commands` | Idempotent command and payload checksum at an expected ledger version |
| `ledger_events` | Append-only fills and cash-transfer events with monotonically increasing versions |
| `ledger_valuation_snapshots` | Checksum-protected dated account valuation payloads |

Current holdings, cash, FIFO lots, realized P&L, and journal rows are derived
from ledger events. They are not independently mutable tables. The expected
version provides optimistic concurrency; stale commands fail instead of
overwriting newer transactions.

## Action proposals

| Table | Role |
|---|---|
| `action_proposals` | Review state, strategy/source, date, expected ledger version, immutable artifact, and encoded decisions |
| `action_proposal_events` | Generated, amended, approved, rejected, and processed lifecycle events |

Generated strategy proposals and generated stop proposals cannot be processed
into ledger fills. A proposal whose source is `manual` represents execution
facts entered by the user and may be processed after approval. The immutable
artifact is checked before processing, and retry recovery can restore a missing
SQL projection from the proper artifact category.

## Broker execution

| Table | Role |
|---|---|
| `broker_orders` | Execution intent, account/proposal identity, order facts, broker ID, state, and timestamps |
| `broker_execution_events` | Append-only submission, status, fill, and reconciliation events |
| `broker_baskets` | Grouped order intent and basket state |
| `broker_basket_orders` | Order membership and slice ordering within a basket |

The gateway remains disabled by default. Reconciliation posts each confirmed
fill once by using broker/order fill identity as the ledger idempotency
boundary.

## Intraday and operational state

| Table | Role |
|---|---|
| `index_poller_leases` | Poll interval, enabled state, last job, success, and error |
| `intraday_stream_leases` | Desired stream state, account, token count, heartbeat, and error |
| `intraday_stop_alerts` | Immutable stop observations; alerts never create fills |

Background poller exceptions are logged and copied to `last_error`, making a
failed loop observable without terminating the server.

## Backup and portability

The database plus its schema is the complete active runtime dataset. Do not
copy only the main file while WAL writes are active. Stop the application or
use:

```powershell
poetry run screener-ops backup-sqlite instance/system.db backups/system.db
```

Token files and local secrets are deliberately outside the database and must
be transferred separately through a secure channel.
