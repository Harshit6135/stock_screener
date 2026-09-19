# Stock Screener

Local modular monolith for Indian-market research, strategy rankings,
backtesting, and real portfolio accounting.

## Run

```powershell
poetry install --with dev
poetry run python run.py
```

Or, with the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe run.py
```

Open `http://127.0.0.1:5000/app`. The application is loopback-only by default,
has no local authentication layer, and uses Kite OAuth as its only
authentication flow.

All current runtime data and compressed artifacts are stored in
`instance/system.db`. Old split databases are not used by the application.

## Kite setup

Configure the shared market-data profile:

```text
MARKET_DATA_KITE_API_KEY
MARKET_DATA_KITE_API_SECRET
```

Authorize it at `/integrations/kite`; the token defaults to
`access_token.txt`.

Portfolio Kite credentials are intentionally separate:

```text
PORTFOLIO_KITE_API_KEY
PORTFOLIO_KITE_API_SECRET
```

Authorize them at `/integrations/kite/portfolio`; the token defaults to
`portfolio_access_token.txt`. Live broker order placement remains disabled by
default.

## Current architecture

- Durable local jobs and background worker
- NSE/BSE instrument matching with NSE-preferred ISIN deduplication
- YFinance day-zero market-cap universe screening
- Kite historical bars and index quotes
- Immutable YAML-backed strategy revisions
- Pandas TA allowlisted indicator catalogue
- Revision-aware features, scores, and rankings
- Append-only portfolio ledger for manual and Kite-confirmed transactions
- Isolated backtesting with total return, CAGR, XIRR, annual returns, drawdown,
  risk ratios, fills, and equity history
- Compressed immutable artifacts inside the same SQLite database

Important current limitations:

- The existing 1,744-row universe is from an interrupted build and must be
  rebuilt after atomic universe publication is implemented.
- No validated 2015-present market/research rebuild exists in the active DB.
- Strategy YAML still dispatches to two registered custom whole-strategy
  implementations; the generic indicator DAG executor remains pending.
- Processing a strategy proposal can still create model-priced fills and must
  not be used for the real portfolio until converted to intent-only behavior.

## Development

```powershell
poetry run python -m pytest tests -q
poetry run screener-ops check-sqlite instance/system.db
poetry run screener-ops backup-sqlite instance/system.db backups/system.db
```

See the [current application guide](docs/current/V4%20usage%20guide.md) for
operations and [remaining implementation work](docs/current/Consolidated%20pending%20items.md)
for the pending-only backlog.
