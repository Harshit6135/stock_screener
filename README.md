# Stock Screener

Local-first research and portfolio operations for NSE equities. The application
provides market and universe data, strategy rankings, backtests, portfolio
accounting, reviewable action proposals, and optional Kite integrations.

## Run locally

Requirements: Python 3.13 and Poetry 2.x.

```powershell
poetry install --with dev
poetry run python run.py
```

Or use the already-created environment:

```powershell
.\.venv\Scripts\python.exe run.py
```

Open [http://127.0.0.1:5000/](http://127.0.0.1:5000/). The default local data
directory is `instance/`; change it with `SCREENER_DATA_DIRECTORY`. The app
binds to localhost by default.

Kite credentials are optional for read-only research. Configure them through
the documented `MARKET_DATA_KITE_*` or `PORTFOLIO_KITE_*` environment variables,
or the ignored local `local_secrets.py` file. Never commit credentials or access
tokens. Live portfolio execution is disabled unless explicitly configured.

## Documentation

- [User guide](docs/user/workflows.md): screen-by-screen instructions and common workflows.
- [System architecture](docs/development/architecture.md): module ownership and data flows.
- [Developer guide](docs/development/setup.md): configuration, commands, code conventions, and review workflow.
- [API and data contracts](docs/reference/api-and-data.md).
- [In-app guide index](docs/reference/README.md).
- [Documentation index](docs/README.md) for current guides.

## Main pages

`/` Home · `/universe` Universe · `/pipeline` Pipeline · `/rankings` Rankings ·
`/backtest` Backtest reports · `/actions` Action proposals · `/settings` Settings ·
`/logs` Logs · `/wiki` Guide.

## Project commands

```powershell
poetry run screener-ops --help
poetry run ruff check src tests run.py tools
poetry run python -m pytest -q
```

See the [developer guide](docs/development/setup.md) before running checks or changing
runtime state. Backups and generated research output should be handled through
the operations commands documented there.
