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

- [Documentation index](docs/README.md)
- [User guide](docs/user-guide.md)
- [Operations](docs/wiki/operations.md)
- [API and data reference](docs/wiki/api-and-data.md)
- [Research and strategies](docs/wiki/research-and-strategies.md)
- [Portfolio and actions](docs/wiki/portfolio-and-actions.md)
- [Troubleshooting](docs/wiki/troubleshooting.md)
- [Authoritative overhaul plan](docs/Overhaul_Plan.md)
- [Phase plans and acceptance evidence](docs/phases/README.md)
- [Current repair status](docs/phases/repair-status.md)

Interactive CodeTour files are under `.tours/`. With the VS Code CodeTour
extension installed, use them to walk through the application overview,
strategy creation, market-data flow, research flow, and portfolio flow.

## Current implementation

- The manual pipeline uses immutable daily NIFTY 500 snapshots and six NSE benchmarks.
- Active strategies are `momentum` and `positional_trend_following`.
- Strategy definitions and published artifacts retain immutable revisions and provenance.
- Backtests run in isolated simulations and never write portfolio fills.
- Action proposals require approval and broker orders reconcile actual fills.
- Live execution starts disabled with its kill switch active.
- Phase completion remains under review; the [repair status](docs/phases/repair-status.md)
  distinguishes verified behavior from outstanding work.

## Validation

```powershell
poetry run python -m pytest -q
poetry run ruff check src tests run.py
poetry run python -m compileall -q src tests run.py
```

Outstanding phase work and validation evidence are recorded in
[repair status](docs/phases/repair-status.md).
