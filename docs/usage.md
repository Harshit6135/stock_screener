# Usage guide

## Requirements

- Python 3.13
- Poetry, or an existing repository `.venv`
- Kite application credentials for provider-backed market data
- Separate Kite portfolio credentials only when broker integration is needed

Install:

```powershell
poetry install --with dev
```

## Configuration

Market-data profile:

```text
MARKET_DATA_KITE_API_KEY
MARKET_DATA_KITE_API_SECRET
SCREENER_MARKET_DATA_KITE_ACCESS_TOKEN_PATH   # optional
```

Portfolio profile:

```text
PORTFOLIO_KITE_API_KEY
PORTFOLIO_KITE_API_SECRET
SCREENER_PORTFOLIO_KITE_ACCESS_TOKEN_PATH     # optional
SCREENER_PORTFOLIO_KITE_LIVE_EXECUTION=false
```

Runtime:

```text
SCREENER_DATA_DIRECTORY=instance
SCREENER_RUN_WORKER=true
SCREENER_WORKER_CONCURRENCY=2
SCREENER_WAITRESS_THREADS=8
SCREENER_HOST=127.0.0.1
SCREENER_FULL_STARTUP_RECOVERY=false
```

Do not reuse the market-data credentials for portfolio execution. Live order
placement should remain disabled until the pending real-account acceptance
work is complete.

## Start and authorize

```powershell
poetry run python run.py
```

Without Poetry:

```powershell
.\.venv\Scripts\python.exe run.py
```

Open `http://127.0.0.1:5000/app`. Market-data OAuth is available at
`/integrations/kite`; portfolio OAuth is at `/integrations/kite/portfolio`.
Kite access tokens normally expire daily, so authorize again when required.

The application binds to loopback by default. Do not expose it to a network;
there is intentionally no local authentication layer.

## Build the universe

Submit the `reference.enrich-day0-universe` job through the Operations UI/API.
The default market-cap threshold is ₹500 crore. The job synchronizes Kite NSE
and BSE references, performs ISIN deduplication, enriches through YFinance, and
atomically publishes the completed membership.

The first build can take considerable time because requests are deliberately
spaced to reduce rate-limit pressure. An interrupted scan does not become
active. Inspect its durable job events instead of assuming a non-empty raw
membership is complete.

## Refresh market history

Use:

```text
POST /api/v2/market/refresh
```

Example body:

```json
{
  "start_date": "2015-01-01",
  "end_date": "2026-09-18"
}
```

Each child Kite request spans at most 365 calendar days. Repeat/retry is safe:
completed provider coverage windows are skipped. Market refresh includes the
fixed universe, all open holdings, and NIFTY 500.

Inspect:

```text
GET /api/v2/market/coverage
GET /api/v2/market/bars/<symbol>?exchange=NSE
GET /api/v2/market/indices/quotes
GET /api/v2/operations/jobs
```

## Run research

Submit a completed date or a range of at most 365 days:

```text
POST /api/v2/pipelines/research
```

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-09-18",
  "strategies": ["strategy1", "strategy2"],
  "orchestrate_data": false
}
```

By default the pipeline expands weekdays. Supply `trading_dates` when an
authoritative exchange-session set is available. The generic exchange calendar
planner remains pending.

Monitor and control:

```text
GET  /api/v2/pipelines/research/<pipeline-id>
POST /api/v2/pipelines/research/<pipeline-id>/stages/<stage-name>/retry
POST /api/v2/pipelines/research/<pipeline-id>/cancel
```

Read rankings:

```text
GET /api/v2/research/ranking-weeks?strategy_id=strategy1
GET /api/v2/research/rankings?strategy_id=strategy1&week_end=YYYY-MM-DD
```

## Run backtests

Use the Backtest UI or submit `backtest.run` as a durable job. Select an active
strategy revision, completed date range, opening capital, and explicit
pyramiding setting.

Reports distinguish:

- total return for the complete period;
- CAGR/annualized return;
- XIRR based on dated cash flows;
- per-calendar-year returns;
- maximum drawdown and risk ratios; and
- fill/order count and equity history.

Stored reports:

```text
GET /api/v2/backtests/runs
GET /api/v2/backtests/runs/<run-id>
GET /api/v2/backtests/runs/<run-id>/attribution
GET /api/v2/backtests/walk-forward/<walk-forward-id>
```

Do not treat results as validated strategy evidence until the full
2015-present market and research rebuild has passed the checks in pending work.

## Use the real portfolio

Create an account through `/portfolio` or:

```text
POST /api/v2/portfolio/accounts
```

Use `portfolio` as the intended primary account identity for new workflows.
Manual fills must represent transactions that actually completed. Supply a
stable idempotency key, the current expected ledger version, symbol, side,
units, actual price, and date.

Portfolio read APIs include account projection, events, journal, ticker,
valuation, valuation history, and summary under
`/api/v2/portfolio/accounts/<account-id>`.

Generated action proposals may be reviewed and approved, but cannot be
processed as fills. Broker execution intent and complete reconciliation remain
partly pending; keep Kite live execution disabled.

## Main API areas

| Area | Prefix |
|---|---|
| Operations and jobs | `/api/v2/operations` |
| Reference data | `/api/v2/reference` |
| Market data | `/api/v2/market` |
| Research | `/api/v2/research` |
| Research pipelines | `/api/v2/pipelines` |
| Indicators | `/api/v2/indicators` |
| Strategy revisions | `/api/v2/strategies` |
| Portfolio ledger | `/api/v2/portfolio` |
| Actions | `/api/v2/actions` |
| Backtests | `/api/v2/backtests` |
| Kite OAuth | `/integrations/kite` |

## Stop the application

Use `Ctrl+C` in the terminal running Waitress. Stop the process before copying
the raw database file so WAL changes are checkpointed. See
[Operations](operations.md) for backup and recovery commands.
