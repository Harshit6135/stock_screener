# V4 usage guide

This guide describes the current V4 application in `stocks_screener_v2`. V4 is
a local, single-operator modular monolith for reproducible market research and
paper-portfolio operations. It is not a live-trading system: the broker
gateway, order intents, and execution controls exist as safety-gated seams, but
live Kite order placement is disabled by default.

## 1. What the application does

The normal operating loop is:

```text
Kite/reference files
        |
        v
instrument identity + market bars + index quotes
        |
        v
features -> percentiles -> scores -> rankings
        |
        +--> backtest reports
        +--> dated paper-action proposals -> review -> paper ledger
                                      |
                                      v
                           valuation, journal, risk read models
```

All long-running work is represented by a durable job. HTTP submission only
queues work; a worker claims, leases, executes, and records the result. The
research pipeline is a durable coordinator over child jobs, so a pipeline can
be inspected, retried, cancelled, and resumed after a process restart.

## 2. Architecture

### Runtime composition

`run.py:create_app()` builds the application and wires `ApplicationServices`.
The service object composes the following bounded areas:

| Area | Responsibility | Main implementation |
| --- | --- | --- |
| Web adapters | Flask blueprints, request validation, JSON/SSE readback | `src/application/*_web.py` |
| Operations | Durable jobs, leases, retries, event cursors, cancellation | `jobs.py`, `worker.py`, `web.py` |
| Reference data | NSE/BSE/Kite identity, token history, sectors and publications | `reference_web.py`, `market_jobs.py` |
| Market data | Bars, coverage, index quotes, corporate actions, intraday alerts | `market_repository.py`, `market_web.py` |
| Research | Strategy 1/2 features, percentiles, scores, rankings and anomalies | `research_jobs.py`, `research_web.py` |
| Pipeline | Ordered date-range orchestration across strategies | `pipeline_jobs.py`, `pipeline_web.py` |
| Portfolio | Append-only cash/fill ledger, FIFO lots, valuation and journal | `execution_gateway/ledger.py`, `portfolio_web.py` |
| Actions | Generate, amend, approve/reject and process paper proposals | `action_jobs.py`, `actions_web.py` |
| Backtests | Historical replay, stress, walk-forward and attribution reports | `backtest_jobs.py`, `backtest_web.py` |
| Configuration | Draft, approval and effective-date strategy revisions | `strategy_configs.py`, `configs_web.py` |

The domain modules (`src/platform_kernel`, `src/market_data`,
`src/indicators`, `src/strategies`, `src/portfolio_accounting`, and
`src/portfolio_engine`) are deliberately usable without Flask. Web code is an
adapter around those domain contracts; it should not become the source of
portfolio or research rules.

### Persistence and lineage

The default data directory is `instance/`:

```text
instance/
  system.db       all durable data, compressed artifacts, and migration state
  access tokens    ignored deployment-local files, if configured
```

`system.db` contains independently migrated namespaces for operations,
catalog, market data, research, strategy configuration, portfolio ledger,
actions, backtests, imports, and pipeline state. The application runs reviewed
SQLite migrations; it does not call a global ORM `create_all` on startup.
Artifact payloads are compressed in the same database, so a normal deployment
does not create one directory and multiple JSON files per research result.

Published outputs are content-addressed/cataloged artifacts. A manifest records
the category, checksum, quality, effective/as-of date, input identifiers and
upstream artifact IDs. This makes a ranking, action proposal, or backtest
reproducible and allows downstream artifacts to be qualified or invalidated
when corporate-action facts change.

The job store is idempotent by `fingerprint`. Reusing a fingerprint with a
different command or payload is rejected. Running the same paper proposal or
ledger command again with the same idempotency key does not create a second
financial event.

### Worker model

V4 has one local writer worker (`local-writer`). It claims queued jobs with a
lease, emits events, renews the lease at cooperative checkpoints, and retries
retryable failures up to the job's attempt limit. A failed job can be retried
explicitly; a running job can be cancelled cooperatively.

When started through `run.py`, a daemon background worker starts by default.
For controlled operation, set `SCREENER_RUN_WORKER=false` and use the CLI or
the protected `/api/v2/operations/worker/*` endpoints. This is useful for
tests, batch runs, and debugging.

## 3. Installation and configuration

Requirements are Python 3.13+ and Poetry.

```powershell
cd C:\Users\harsh\Documents\GitHub\stocks_screener_v2
$env:SCREENER_OPERATOR_TOKEN = "choose-a-local-secret"
poetry install --with dev
```

The operator token is required before any state-changing operation can run.
Send it as `X-Operator-Token`; do not put it in URLs or browser-visible page
content. Useful local settings are:

```powershell
$env:SCREENER_DATA_DIRECTORY = "instance"
$env:SCREENER_SECRET_KEY = "another-local-secret"
$env:SCREENER_HOST = "127.0.0.1"
$env:SCREENER_RUN_WORKER = "true"
$env:SCREENER_AUTOMATIC_PAPER_MODE = "true"
```

The default service is loopback-only at `http://127.0.0.1:5000`. A non-loopback
bind requires both `SCREENER_ALLOW_NETWORK_BIND=true` and a TLS-capable reverse
proxy. V4 is intentionally a single local operator deployment; it does not
provide multi-user identity or RBAC.

When `SCREENER_AUTOMATIC_PAPER_MODE=true`, newly saved strategy revisions are
activated automatically and generated paper proposals are approved and
processed by the worker. If market-data credentials are configured but the
daily token is missing, `/` redirects to Kite authorization. This setting is
paper-only and does not enable live broker execution. In this mode the Kite
authorization page starts the OAuth redirect without asking for the local
operator token; the only expected user input is Kite credentials/2FA.

### Kite market-data profile

Set `MARKET_DATA_KITE_API_KEY` and `MARKET_DATA_KITE_API_SECRET`. Authorize from
`/integrations/kite`; the callback is
`/integrations/kite/market-data/callback`. The daily token defaults to
`access_token.txt`, or can be moved with
`SCREENER_MARKET_DATA_KITE_ACCESS_TOKEN_PATH`.

The repository includes `data/imports/NSE.csv` and `data/imports/BSE.csv` for
identity matching. Kite credentials and token files are deployment-local and
must not be committed.

### Portfolio profile

`PORTFOLIO_KITE_API_KEY` and `PORTFOLIO_KITE_API_SECRET` are isolated from the
market-data credentials. Its callback is
`/integrations/kite/portfolio/callback`, and its default token is
`portfolio_access_token.txt`. Keep
`SCREENER_PORTFOLIO_KITE_LIVE_EXECUTION` false. The current portfolio workflow
uses historical prices and the paper ledger even when portfolio credentials
are configured.

## 4. Start and verify the service

Start the default local server:

```powershell
poetry run python run.py
# equivalent entry point:
poetry run screener
```

Expected behavior is a message showing Waitress on port 5000. Verify process
liveness and durable-store readiness in another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health/live
Invoke-RestMethod http://127.0.0.1:5000/health/ready
Start-Process http://127.0.0.1:5000/app
```

`/health/live` checks only that the process responds. `/health/ready` checks
that all required SQLite namespaces accept a query; it does not prove Kite
credentials or provider connectivity.

The current V4 browser pages are `/app`, `/actions`, `/backtest`, `/pipeline`,
`/configs`, and `/portfolio`. `/` redirects to `/app`. `/dashboard` and the
`/api/v1` surface are retained as legacy compatibility workflows; new clients
should use `/api/v2`.

## 5. First-time data and research workflow

### Step 1: authorize and sync identity

After configuring Kite, open `/integrations/kite` and complete the market-data
authorization. Then submit an instrument-sync job. The `fingerprint` should be
stable for the same intended command:

```powershell
$headers = @{ "X-Operator-Token" = $env:SCREENER_OPERATOR_TOKEN }
$body = @{
  fingerprint = "reference-sync-nse-2026-09-13"
  kind = "reference.sync-kite-instruments"
  payload = @{}
} | ConvertTo-Json

$job = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:5000/api/v2/operations/jobs `
  -Headers $headers -ContentType "application/json" -Body $body
$job
```

Use `reference.sync-bse-instruments` separately when BSE identity is needed.
Read completed identity with `GET /api/v2/reference/instruments` and inspect
token changes with `/api/v2/reference/instruments/<instrument-id>/token-history`.

### Step 2: process jobs

With the default server, the background worker processes the queue. For a
manual worker loop or a process with background work disabled:

```powershell
poetry run screener-ops work-once instance
```

Repeat until it prints `idle`. The HTTP equivalents are:

```text
GET  /api/v2/operations/jobs/<job-id>
GET  /api/v2/operations/jobs/<job-id>/events?after=0
POST /api/v2/operations/worker/work-once
GET  /api/v2/operations/worker/status
```

The last two worker controls require the operator token. A job response reports
`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, or `CANCELLED`; event IDs are
cursor-based, so persist the last event ID when polling.

### Step 3: ingest market data

For an existing V3 market database, queue `market.import-v3-bars`; the source
is opened read-only. For Kite history, use `market.fetch-kite-bars` with the
symbol, exchange, and bounded date range accepted by the job handler. The
application limits each market fetch to 365 calendar days. Coverage is
available at:

```text
GET /api/v2/market/coverage
GET /api/v2/market/bars/<symbol>?exchange=NSE
GET /api/v2/market/indices/quotes
```

For a larger refresh, `POST /api/v2/market/refresh` plans bounded jobs and
`POST /api/v2/market/reconcile` publishes reconciliation output.

### Step 4: run the dated research pipeline

Submit a completed date (or a range no longer than 365 days):

```powershell
$body = @{
  as_of_date = "2026-09-11"
  strategies = @("strategy1", "strategy2")
  orchestrate_data = $false
} | ConvertTo-Json

$pipeline = Invoke-RestMethod `
  -Method Post -Uri http://127.0.0.1:5000/api/v2/pipelines/research `
  -Headers $headers -ContentType "application/json" -Body $body
$pipeline

Invoke-RestMethod `
  http://127.0.0.1:5000/api/v2/pipelines/research/$($pipeline.pipeline_id)
```

Dates must be earlier than the current India date. A single-date pipeline
queues daily strategy jobs and then weekly ranking jobs when the date is a
Friday. A range queues daily jobs for each strategy/session and weekly jobs
for Fridays. Use `orchestrate_data=true` when the pipeline should first queue
reference sync, market refresh, and reconciliation; use `false` when market
inputs are already present. An explicit `trading_dates` list is recommended
when replaying a known exchange-session snapshot.

The logical calculation chain is:

```text
reference/market prerequisites
  -> daily Strategy 1/2 features
  -> percentile snapshots
  -> score snapshots
  -> Friday ranking snapshots
  -> ranking read models and downstream actions/backtests
```

Read immutable outputs with
`GET /api/v2/research/{features,percentiles,scores,rankings}/<artifact-id>`
or query rankings by week with
`GET /api/v2/research/rankings?week_end=YYYY-MM-DD&limit=20`.

If a stage fails, retry only that stage with
`POST /api/v2/pipelines/research/<pipeline-id>/stages/<stage-name>/retry`.
Cancel with `POST /api/v2/pipelines/research/<pipeline-id>/cancel`.

## 6. Configuration, actions, and paper portfolio

### Strategy configuration

Create a draft revision with `POST /api/v2/configs/<strategy-id>/revisions`,
review it with `GET /api/v2/configs/<strategy-id>/revisions`, then approve it
with `POST /api/v2/configs/revisions/<revision-id>/approve`. Revisions have an
effective date and risk policy; the active revision is captured in action and
backtest lineage. Use the `/configs` page for the same workflow.

In automatic paper mode, the create request activates the revision using the
current India date, so the separate approval request is unnecessary.

### Paper actions

Generate a dated proposal using
`actions.generate-paper-proposal` or the `/actions` page. The request requires
`account_id`, `strategy_id`, a completed `action_date`, and either an explicit
`max_positions` from 1 through 20 or an active configuration that supplies the
limit. Review proposals using:

```text
GET  /api/v2/actions/proposals?account_id=<account-id>
GET  /api/v2/actions/proposals/<proposal-id>
POST /api/v2/actions/proposals/<proposal-id>/approve
POST /api/v2/actions/proposals/<proposal-id>/reject
POST /api/v2/actions/proposals/<proposal-id>/process
```

Processing an approved proposal writes version-checked paper fills to the
ledger. It does not submit a broker order. A repeated process request is
idempotent. Manual BUY/SELL intents and immutable amendments are available
through the same action API.

In automatic paper mode, generated proposals are approved and processed by
the worker, including proposals submitted through the V1 compatibility
endpoint. Proposal and processing events remain in the audit trail.

### Paper account

Open an account:

```powershell
$body = @{ account_id = "research-paper"; opening_cash = "100000" } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5000/api/v2/portfolio/accounts `
  -Headers $headers -ContentType "application/json" -Body $body
```

Inspect `GET /api/v2/portfolio/accounts/<account-id>` for cash, FIFO lots, and
realised P&L. Record manual fills or cash transfers with an idempotency key and
the account's current `expected_version`; stale versions are rejected to
prevent lost updates. Read valuation at a date with
`GET /api/v2/portfolio/accounts/<account-id>/valuation?as_of_date=YYYY-MM-DD`.
Add `&persist=1` to save a checksum-verified valuation snapshot. The
`/portfolio` page exposes the account read models and ticker stream.

## 7. Backtesting and result readback

Backtests are queued as `backtest.run` jobs. They replay dated rankings against
later daily bars using paper-only execution assumptions. Reports are immutable
and cataloged. Related jobs support stress tests, walk-forward evaluation, and
attribution. Read results with:

```text
GET /api/v2/backtests/runs
GET /api/v2/backtests/runs/<run-id>
GET /api/v2/backtests/walk-forward/<walk-forward-id>
GET /api/v2/backtests/runs/<run-id>/attribution
```

The `/backtest` page lists saved runs and exposes report detail. Treat report
quality flags, stale/missing bars, corporate-action qualification, and
survivorship/universe lineage as part of the result—not as optional metadata.

## 8. API conventions and safety rules

- JSON mutations require `X-Operator-Token`. If the token is not configured,
  mutations return `503`; an incorrect token returns `401`.
- Read-only health and most public research/market readbacks do not require
  the token. Portfolio, action, configuration, and operational endpoints are
  operator-protected.
- Use ISO dates (`YYYY-MM-DD`) and timezone-aware timestamps where accepted.
- Use a stable fingerprint for every submitted job and a stable idempotency key
  for every ledger command.
- Never treat a `202 Accepted` job submission as completion; poll job or
  pipeline status.
- Never enable live execution merely because portfolio Kite credentials exist.
  The current supported execution path is paper-only.
- Back up `instance/system.db` before migration or bulk maintenance. The V3
  market source used by import is read-only, but the destination V4 stores are
  mutable.

## 9. Testing and quality checks

Install the development dependencies, then run the focused test suite:

```powershell
poetry run python -m pytest tests -q
```

Run the repository’s coverage gate:

```powershell
poetry run python -m pytest tests --cov=src --cov=run --cov-fail-under=85 -q
```

Static and security checks:

```powershell
poetry run ruff format --check src tests run.py
poetry run ruff check src tests run.py
poetry run mypy src run.py
poetry run bandit -q -r src run.py
```

Equivalent Make targets are `make test`, `make lint`, `make type`, and
`make security` in environments that provide `make`.

The web tests build an isolated Flask app with a temporary data directory, so
they do not need a running server or real Kite credentials. A minimal smoke
check is:

```powershell
poetry run python -c "from run import create_app; app=create_app(); print(app.test_client().get('/health/live').json)"
poetry run screener-ops check-sqlite instance/system.db
```

For a local backup/restore drill:

```powershell
poetry run screener-ops backup-sqlite instance/system.db backups/system.db
poetry run screener-ops check-sqlite backups/system.db
poetry run screener-ops restore-sqlite backups/system.db instance/restored-system.db
poetry run screener-ops check-sqlite instance/restored-system.db
```

### Test without Poetry

If Poetry is not available on `PATH`, the repository-managed virtual
environment can run the same checks directly from PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m pytest tests --cov=src --cov=run --cov-fail-under=85 -q
```

The equivalent CLI entry point is available after installation as
`.\.venv\Scripts\screener-ops.exe`; use it for `work-once`, `check-sqlite`,
and backup/restore commands when the `poetry run` wrapper is unavailable.

## 10. Request and data-flow reference

The following is the complete supported V4 operating sequence. Each arrow is
also a persistence boundary: the next stage consumes a stored record or
artifact, not an in-memory result from the previous HTTP request.

```text
operator/browser or API client
        |
        |  POST mutation + X-Operator-Token
        v
JobStore (SQLite: fingerprint, payload, lease, attempts, events)
        |
        |  local-writer claims job
        v
domain/application handler
  |             |                 |
  |             |                 +--> paper ledger events / action events
  |             +--> ArtifactPublisher -> ArtifactStore + catalog manifest
  +--> child jobs (refresh and research pipeline coordination)
        |
        v
GET read models, job status/events, or immutable artifact payloads
```

`run.py` creates one `ApplicationServices` object and injects it into Flask
blueprints. The blueprints validate HTTP input and authorization; stores and
domain services own business rules. The background worker is a daemon thread
in the same process and uses the `local-writer` lease. With
`SCREENER_RUN_WORKER=false`, the exact same handlers are driven by
`screener-ops work-once` or `POST /api/v2/operations/worker/work-once`.

### V4 route map

| Surface | Main routes | Purpose | Default authorization |
| --- | --- | --- | --- |
| Health | `/health/live`, `/health/ready` | Process and SQLite readiness | Public |
| Operator pages | `/app`, `/pipeline`, `/configs`, `/actions`, `/portfolio`, `/backtest` | Browser readback and controlled operations | Page load is local; mutations send the operator token |
| Operations | `/api/v2/operations/jobs`, `/api/v2/operations/worker/*` | Submit, inspect, cancel and execute durable jobs | Mutations protected |
| Reference | `/api/v2/reference/*` | Instruments, tokens, sectors and reference artifacts | Reads public; writes protected |
| Market | `/api/v2/market/*` | Bars, coverage, indices, refresh, reconciliation and alerts | Reads public; writes protected |
| Research | `/api/v2/research/*` | Snapshots, rankings, anomalies and parity artifacts | Readbacks public; calculations protected |
| Pipeline | `/api/v2/pipelines/research/*` | Coordinate data, daily and weekly stages | Submit/retry/cancel protected |
| Config | `/api/v2/configs/*` | Draft, inspect and approve immutable revisions | Reads public; writes protected |
| Portfolio | `/api/v2/portfolio/accounts/*` | Paper accounts, fills, cash, valuation, journal and events | Protected |
| Actions | `/api/v2/actions/*` | Paper proposals, decisions, amendments and processing | Protected |
| Backtests | `/api/v2/backtests/*` | Saved paper replay reports and readback | Reads public; publishing protected |
| Kite auth | `/integrations/kite`, `/integrations/kite/portfolio` | Separate market-data and portfolio authorization flows | Local operator flow |

The registered `/api/v1/*` compatibility routes and `/dashboard` are retained
for migration and parity work. They are not the preferred V4 client contract;
their payloads and behavior follow the compatibility adapter, not the V2
schemas above.

## 11. Restart, recovery, and troubleshooting

1. Check `/health/ready` and `screener-ops check-sqlite instance/system.db`.
2. Check `/api/v2/operations/worker/status`; if background work is disabled,
   run `screener-ops work-once instance` until it reports `idle`.
3. For a job that is not terminal, inspect its events with `after=<last id>`;
   do not submit a duplicate job with a new fingerprint.
4. For a failed stage, fix the input/provider issue and retry that pipeline
   stage. A retry creates a new attempt while preserving the pipeline history.
5. If the process stopped during publication, submit `artifacts.recover` or
   restart the application; recovery reconciles the artifact catalog with the
   compressed payloads in `system.db`.
6. Before migrations or bulk maintenance, make a verified SQLite backup.

Common interpretations:

- `202` means queued/accepted, not successful. Poll the job or pipeline.
- `/health/live` can be healthy while Kite is unavailable; provider checks are
  intentionally outside liveness/readiness.
- A `FAILED` research pipeline can have useful earlier artifacts, but its
  downstream ranking/action stages must not be treated as complete.

## 12. Operational limitations

V4 remains a local single-operator deployment. Production live order placement,
multi-user accounts/RBAC, deployment-owned process supervision for intraday
streams, automatic live delisting liquidation, and exact equivalence for all
historical tax/fee inputs remain release decisions or partial migrations. For
the authoritative feature status, see the [consolidated delivery status](Consolidated%20pending%20items.md).
