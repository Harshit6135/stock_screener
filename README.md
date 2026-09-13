# Stock Screener

Backend-only modular monolith for reproducible market research and paper
portfolio operations. The retired Flask-Smorest, SQLAlchemy, and UI stack has
been removed.

## Run

```powershell
$env:SCREENER_OPERATOR_TOKEN = "choose-a-local-secret"
poetry install --with dev
poetry run python run.py
```

The service binds to `127.0.0.1:5000` by default. Read-only health endpoints:
`/health/live` and `/health/ready`. Mutating operations under
`/api/v2/operations` require the `X-Operator-Token` header.

## Development

```powershell
poetry run python -m pytest tests -q
poetry run screener-ops check-sqlite instance/operations.db
```

See [the implementation plan](docs/IMPLEMENTATION_PLAN.md) for the package
boundaries, artifact lineage model, paper-ledger safety gate, and roadmap.
