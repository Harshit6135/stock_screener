# Stock Screener

Local Indian-market research, ranking, backtesting, and real-portfolio
accounting application. It runs as a modular Python monolith, stores all
runtime state and compressed artifacts in one SQLite database, and uses Kite
OAuth as its only authentication flow.

## Start here

```powershell
poetry install --with dev
poetry run python run.py
```

Or use the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe run.py
```

Open `http://127.0.0.1:5000/app`. The default database is
`instance/system.db`.

## Documentation

- [Architecture](docs/architecture.md)
- [Design principles](docs/design.md)
- [Implementation guide](docs/implementation.md)
- [Adding a durable job](docs/adding-a-job.md)
- [Data model](docs/data-model.md)
- [System workflows](docs/workflows.md)
- [Adding a strategy](docs/adding-a-strategy.md)
- [Usage guide](docs/usage.md)
- [Operations](docs/operations.md)
- [Pending work](docs/pending-items.md)

Interactive CodeTour files are under `.tours/`. With the VS Code CodeTour
extension installed, use them to walk through the application overview,
strategy creation, market-data flow, research flow, and portfolio flow.

## Current guarantees

- NSE/BSE instruments are deduplicated by ISIN with NSE preferred.
- A universe is active only after its complete build is committed atomically.
- Market refresh always includes open portfolio holdings and the NIFTY 500
  benchmark in addition to the fixed universe.
- Strategy definitions are immutable, revisioned YAML imports backed by
  canonical JSON in SQLite.
- Backtests are isolated simulations and never write portfolio fills.
- Generated strategy and stop proposals cannot create real ledger fills.
- There is no paper-trading mode and no application authentication layer.

## Validation

```powershell
poetry run python -m pytest -q
poetry run ruff check src tests run.py
poetry run python -m compileall -q src tests run.py
```

The static type-checking backlog and other incomplete work are recorded in
[pending items](docs/pending-items.md).
