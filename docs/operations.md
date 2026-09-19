# Operations

## Runtime processes

The default process contains Waitress, a background durable-job worker, and an
index poller when Kite market credentials are configured. Set
`SCREENER_RUN_WORKER=false` when the web process should not execute queued jobs.

Process one job manually:

```powershell
poetry run screener-ops work-once instance
```

The worker concurrency defaults to two. SQLite still serializes writes, so
increasing worker count is useful mainly for provider latency and should be
tested before raising it substantially.

### Waitress task queue warning

`WARNING:waitress.queue:Task queue depth is 1` means every Waitress request
thread was busy and one incoming HTTP request waited briefly. It is Waitress's
web-request queue, not the durable application job queue, and does not indicate
lost market or research work.

The overview page loads rankings, index quotes, and worker state concurrently.
With the previous three-thread setting, the page request plus those three calls
could briefly produce a queue depth of one. The default is now eight threads
and can be changed with `SCREENER_WAITRESS_THREADS`. An occasional depth of one
is harmless; repeated or growing depths indicate a slow/blocking endpoint or
too few request threads and should be investigated.

## Job operations

A `202 Accepted` response means a job was queued, not that it completed. Use
the Operations UI or `/api/v2/operations` to inspect status and events.

Statuses are `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, and `CANCELLED`.
Running jobs hold a lease and claim token. A worker heartbeat extends the
lease. Expired running jobs can be requeued; failed jobs can be retried while
within their configured attempt policy.

Before retrying, inspect `last_error` and progress events. Common categories:

- missing/expired Kite token;
- provider connectivity or rate limiting;
- unresolved reference identity/token;
- incomplete prerequisite market coverage;
- malformed strategy definition;
- stale ledger version; and
- invalidated or missing artifact.

## Kite connectivity

If authorization reports that Python cannot connect to `api.kite.trade:443`,
confirm that the Python executable running this repository is allowed outbound
HTTPS by Windows Firewall or endpoint-security software. Browser access alone
does not prove that the Python process is allowed.

After changing firewall policy:

1. stop the application;
2. restart it from the intended virtual environment;
3. open `/integrations/kite`;
4. complete authorization; and
5. run a small instrument or quote operation before submitting a rebuild.

Market refresh cannot use Kite without valid market-data credentials and a
current access token. Existing rows in SQLite do not prove that the current
process is authenticated.

## Database checks and backup

Check integrity and migrations:

```powershell
poetry run screener-ops check-sqlite instance/system.db
```

Create a safe SQLite backup:

```powershell
poetry run screener-ops backup-sqlite instance/system.db backups/system.db
```

All active records and compressed artifacts are in that database. OAuth token
files and local secrets are separate and intentionally ignored by Git.

Do not copy `system.db` while the server is actively writing unless using the
SQLite backup API. `system.db-wal` and `system.db-shm` are transient and should
not be treated as separate application databases.

## Artifact recovery

Startup removes interrupted staging state. A full catalogue/payload scan is
expensive for a large research database and runs only for an empty/legacy
catalogue or when:

```text
SCREENER_FULL_STARTUP_RECOVERY=true
```

The `artifacts.recover` job can also run recovery explicitly. Recovery verifies
checksums, repairs publication projections, marks missing payloads, and
propagates invalidation through lineage.

## Rebuild order

For an empty or intentionally reset data database:

1. authorize the market-data Kite profile;
2. run the atomic day-zero universe build;
3. verify completed universe metadata and deduplication counts;
4. submit 2015-present market refresh jobs;
5. wait for every child bar job to become terminal;
6. inspect coverage gaps and unresolved instruments;
7. run research for both active strategies;
8. validate sample indicators, scores, and rankings; and
9. run backtests only after those checks pass.

Do not start research while the source market rebuild is known to be incomplete
unless the run is explicitly a partial diagnostic.

## Data validation checklist

- Active membership count equals its completion-state count.
- No duplicate active ISIN exists.
- NSE is selected when both NSE and BSE listings exist.
- NIFTY 500 coverage spans the research period.
- Every open holding is included in refresh planning.
- Coverage windows span all requested ranges.
- Empty pre-listing windows are recorded rather than failed.
- Bar OHLC relationships and volume are valid.
- Daily score counts and weekly rank counts are plausible.
- Artifacts have valid checksums and upstream lineage.
- Strategy IDs and revision IDs match the intended run.
- Backtest start/end dates and total versus annualized returns are labeled
  correctly.

## Health endpoints

`GET /health/live` proves the web process responds. `GET /health/ready` proves
the required local SQLite migration namespaces can be queried. Neither endpoint
tests Kite, YFinance, market freshness, research completeness, or worker health.

## Sharing the application state

Share a SQLite backup rather than generated artifact directories or exports.
The recipient needs compatible code and must provide their own Kite credentials
and tokens. Never include `local_secrets.py`, `.env`, `access_token.txt`, or
`portfolio_access_token.txt`.

## Validation commands

```powershell
poetry run python -m pytest -q
poetry run ruff check src tests scripts run.py
poetry run python -m compileall -q src tests scripts run.py
```

The mypy baseline is not yet clean and is tracked explicitly in
[pending items](pending-items.md).
