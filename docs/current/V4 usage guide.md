# Current application guide

This repository is a local, loopback-only market-research, backtesting, and
portfolio application. It has no application authentication layer. Kite OAuth
is the only authentication flow.

## Runtime and persistence

Start the service with:

```powershell
poetry install --with dev
poetry run python run.py
```

Without Poetry on `PATH`:

```powershell
.\.venv\Scripts\python.exe run.py
```

The server binds to `127.0.0.1:5000` unless explicitly configured otherwise.
`/` redirects to `/app`; health endpoints are `/health/live` and
`/health/ready`.

All runtime records and compressed immutable artifact payloads are stored in:

```text
instance/system.db
```

SQLite may create transient `system.db-wal` and `system.db-shm` files while the
application is running. Stop the application or use SQLite's backup API before
sharing the database. Old split databases are not used by the current runtime.

Long operations are durable jobs. The server starts a background worker by
default. Set `SCREENER_RUN_WORKER=false` to disable it and process one job at a
time with:

```powershell
poetry run screener-ops work-once instance
```

## Kite profiles

Market data and portfolio execution use deliberately separate Kite profiles:

- `MARKET_DATA_KITE_API_KEY` and `MARKET_DATA_KITE_API_SECRET`, authorized at
  `/integrations/kite`; token file defaults to `access_token.txt`.
- `PORTFOLIO_KITE_API_KEY` and `PORTFOLIO_KITE_API_SECRET`, authorized at
  `/integrations/kite/portfolio`; token file defaults to
  `portfolio_access_token.txt`.

The portfolio profile never falls back to market-data credentials. Live order
dispatch is disabled unless `SCREENER_PORTFOLIO_KITE_LIVE_EXECUTION=true`, and
it must remain disabled until the pending real-account rollout is approved.

## Data workflow

### Build the reference universe

`reference.enrich-day0-universe` synchronizes NSE and BSE Kite instruments,
deduplicates equities by ISIN with NSE preferred, then queries YFinance. NSE is
looked up as `<symbol>.NS`; BSE tries `<symbol>.BO` and then
`<security-code>.BO`, with delays between requests. The initial threshold is
strictly greater than ₹500 crore. Existing members are retained on later runs,
and newly eligible listings are added.

The current database contains an interrupted partial universe and must be
rebuilt before market history is trusted. Those rows are inactive: market
refresh accepts a universe only after the full scan is atomically committed
with its resolved, unresolved, selected, threshold, source, and completion
metadata. A failed scan leaves the prior completed universe active.

### Download market data

`POST /api/v2/market/refresh` schedules bounded Kite history jobs. Each request
may span at most 365 calendar days. The selected instruments are:

- fixed-universe members;
- every open portfolio holding, even if it no longer passes screening; and
- the NSE NIFTY 500 benchmark.

No price, turnover, upper/lower-circuit, or market-cap filter is applied by the
backtest engine. A ranked instrument with a bar is eligible for replay. Missing
provider tokens are reported; held instruments with missing identity/token are
reported separately rather than silently excluded.

Read coverage at:

```text
GET /api/v2/market/coverage
GET /api/v2/market/bars/<symbol>?exchange=NSE
GET /api/v2/market/indices/quotes
```

### Run research

Submit completed dates to `POST /api/v2/pipelines/research`. The pipeline
coordinates daily calculation and weekly ranking jobs for active strategy
revisions. It can optionally orchestrate reference and market stages first.
Inspect, retry, or cancel with:

```text
GET  /api/v2/pipelines/research/<pipeline-id>
POST /api/v2/pipelines/research/<pipeline-id>/stages/<stage-name>/retry
POST /api/v2/pipelines/research/<pipeline-id>/cancel
```

The default date expansion uses weekdays. Supply `trading_dates` for a known
exchange-session set until authoritative calendar planning is completed.

## Strategies and indicators

Strategy seeds are YAML files under `strategies/`. On startup they are
validated, canonicalized, stored as immutable SQLite revisions, and activated
when no active revision exists. APIs are under `/api/v2/strategies`.

The current migration is revision-safe but not yet fully generic. The two YAML
definitions still dispatch to registered custom whole-strategy calculations.
A genuinely new strategy therefore may still require Python until the pending
declarative DAG executor is complete.

The approved Pandas TA catalogue is available at:

```text
GET /api/v2/indicators/catalog
GET /api/v2/indicators/catalog/pandas_ta/<indicator-key>
```

The catalogue currently contains EMA, SMA, RSI, ROC, ATR, MACD, Bollinger
Bands, and ADX. It is an allowlist, not a claim that every installed Pandas TA
function is production-approved. The catalogue UI and full conformance/parity
test gate remain pending.

## Portfolio and actions

`/api/v2/portfolio/accounts` is the authoritative append-only portfolio
ledger. Complete manually supplied fills and broker-confirmed fills use the
same ledger. Cash, FIFO lots, valuation, events, and journal readbacks are
available from the account routes and `/portfolio`.

Strategy action proposals are review records, not proof that a transaction
occurred. Processing generated strategy and stop proposals into the ledger is
blocked. Only a manually confirmed transaction can currently be processed, and
it must contain actual completed execution facts. Kite execution intents and
broker reconciliation remain pending.

Backtests are isolated simulations and never write their fills to the
portfolio ledger.

## Backtesting

Submit `backtest.run` as a durable job or use `/backtest`. Reports include at
least total return, CAGR, XIRR, annual returns, maximum drawdown, Sharpe,
Sortino, Calmar, fill count, and an equity curve. Pyramiding can be enabled or
disabled explicitly. Stored report APIs are:

```text
GET /api/v2/backtests/runs
GET /api/v2/backtests/runs/<run-id>
GET /api/v2/backtests/walk-forward/<walk-forward-id>
GET /api/v2/backtests/runs/<run-id>/attribution
```

Current reports cannot be treated as validated strategy evidence until the
2015-present market and research rebuild is completed.

## Main API surfaces

| Area | Routes |
|---|---|
| Jobs and worker | `/api/v2/operations/*` |
| Reference | `/api/v2/reference/*` |
| Market data | `/api/v2/market/*` |
| Research | `/api/v2/research/*` |
| Pipelines | `/api/v2/pipelines/*` |
| Strategy revisions | `/api/v2/strategies/*` |
| Indicator catalogue | `/api/v2/indicators/*` |
| Portfolio | `/api/v2/portfolio/*` |
| Actions | `/api/v2/actions/*` |
| Backtests | `/api/v2/backtests/*` |
| Kite OAuth | `/integrations/kite*` |

## Validation and maintenance

```powershell
poetry run python -m pytest tests -q
poetry run ruff check src tests run.py
poetry run screener-ops check-sqlite instance/system.db
poetry run screener-ops backup-sqlite instance/system.db backups/system.db
```

The static-type gate is not yet clean; `mypy src run.py` is tracked in the
active backlog and should not currently be treated as a passing validation.

If Poetry is unavailable, replace `poetry run python` with
`.\.venv\Scripts\python.exe`.

For a failed job, inspect its durable events and retry the failed job or
pipeline stage. A `202` response means accepted/queued, not completed. Provider
connectivity is intentionally excluded from `/health/live` and
`/health/ready`.

The remaining correctness, strategy-engine, rebuild, and deferred UI work is
tracked only in [Remaining implementation work](Consolidated%20pending%20items.md).
