# Stock Screener

Modular monolith for reproducible market research and portfolio operations.
V4 is an in-progress, breaking migration from the former Flask-Smorest/SQLAlchemy
application. Its old routes, dashboard, and database schemas are not served.
Keep a backup and a read-only copy of v3 data; full behavioral parity is not yet
achieved. Live order dispatch is disabled. The exact feature-by-feature status
is in the [migration ledger](docs/current/V3%20to%20V4%20feature%20migration%20ledger.md).

## Run

```powershell
poetry install --with dev
poetry run python run.py
```

The service binds to `127.0.0.1:5000` by default. Open `/app` for the minimal
rankings, index-quote, job, portfolio-account and action-review page; `/` redirects there unless
handling a Kite callback. Read-only health endpoints:
`/health/live` and `/health/ready`. Mutating operations under
`/api/v2/operations` is local-only. Submit jobs through
`POST /api/v2/operations/jobs`, then run `poetry run screener-ops work-once
instance` to process each queued job. Registered market and research kinds:
`reference.sync-kite-instruments`, `reference.sync-bse-instruments`,
`market.fetch-kite-bars`,
`market.fetch-kite-index-quotes`, `research.calculate-strategy1-day`,
`research.calculate-strategy2-day`, and both strategies' weekly ranking jobs.
Each market fetch is bounded to 365 calendar days. Additional
operations include `system.echo`, `artifacts.recover`, and
`research.build-liquidity-universe`. `actions.generate-portfolio-proposal` accepts
`account_id`, `strategy_id`, a completed `action_date`, and `max_positions`
(1–20). Its proposals must be reviewed and processed
separately. When an approved strategy configuration is active, omit
`max_positions`: that revision supplies the position limit and action policy.
Submit a dated research pipeline with `POST /api/v2/pipelines/research`; it
queues ordered per-strategy daily jobs and, for a Friday, ranking jobs after
the daily stages succeed. Read parent progress at
`GET /api/v2/pipelines/research/<pipeline-id>`.

Read-only results are at `GET /api/v2/reference/instruments`,
`GET /api/v2/reference/tokens/<token>` (optional `as_of=YYYY-MM-DD` and
`exchange`; returns all assignments and an `ambiguous` flag),
`GET /api/v2/reference/instruments/<id>/token-history` (bounded daily
observations with token-change flags),
`GET /api/v2/market/bars/<symbol>` (optional `exchange=BSE`),
`GET /api/v2/market/coverage` (optional `symbol`, `exchange`, `limit`,
`offset`; includes earliest/latest dates, bar count and latest artifact quality),
`GET /api/v2/market/indices/quotes`,
`GET /api/v2/research/{features,percentiles,scores,rankings}/<artifact-id>`, and
`GET /api/v2/research/rankings?week_end=YYYY-MM-DD&limit=20` (optional
`strategy_id=strategy2`).
Liquidity-universe artifacts are at
`GET /api/v2/reference/liquidity-universes/<artifact-id>`.
Portfolio accounts and manual fills are under
`/api/v2/portfolio/accounts`; account detail includes cash, FIFO lots and
realised P&L, with an append-only event readback route. No live broker order
submission is implemented.
Proposal listing, detail, events, approve, reject and
process routes are under `/api/v2/actions/proposals`. Supply `account_id` to
the list route. Processing an approved proposal writes version-checked fills
to the portfolio ledger; a repeated process request is idempotent. Prices are
historical-bar simulation prices, not broker executions.
Strategy configuration drafts and approval are at `/api/v2/configs`; each
revision has a complete risk-policy schema and an explicit effective date.
An active revision also supplies omitted backtest `starting_cash` and
`max_positions`, and is captured in the report lineage.
`backtest.run` replays prior-week rankings against later daily bars into
cataloged reports at `GET /api/v2/backtests/runs` and
`GET /api/v2/backtests/runs/<run-id>`.
Both research strategies were exercised against ten completed Kite sessions
and two weekly rankings. Strategy 2 outputs are provisional because its
fundamental-quality input is a zero placeholder and its scaled-turnover input
is actually relative volume. Production-grade backtest validation, continuous
index polling, and richer action/portfolio UI are
still being migrated. The active v4 pipeline uses Kite and traded turnover,
not yfinance market-cap enrichment.

## Daily Kite authorization

V4 keeps two intentionally isolated Kite profiles:

- Shared market data: configure `MARKET_DATA_KITE_API_KEY` and
  `MARKET_DATA_KITE_API_SECRET`; use the redirect
  `http://127.0.0.1:5000/integrations/kite/market-data/callback` and authorize
  from `/integrations/kite`. Its ignored daily token defaults to
  `access_token.txt`.
- Portfolio: configure `PORTFOLIO_KITE_API_KEY` and
  `PORTFOLIO_KITE_API_SECRET`; use the redirect
  `http://127.0.0.1:5000/integrations/kite/portfolio/callback` and authorize
  from `/integrations/kite/portfolio`. Its ignored token defaults to
  `portfolio_access_token.txt`; it never falls back to the market-data
  credentials.

The application has no local authentication layer and never displays access
tokens. The portfolio profile is used by the Kite broker gateway; manually
recorded and broker-confirmed transactions share the same portfolio ledger. These profiles
are deployment-local; a shared multi-user server needs identity and encrypted
per-user secret storage before it can safely hold team members' credentials.

## Development

```powershell
poetry run python -m pytest tests --cov=src --cov=run --cov-fail-under=85 -q
poetry run screener-ops check-sqlite instance/system.db
poetry run screener-ops backup-sqlite instance/system.db backups/system.db
poetry run screener-ops restore-sqlite backups/system.db instance/restored-system.db
```

See the [documentation index](docs/Index.md) for current architecture material,
the gap review, and the archived v3 reference set.
