# Developer guide

## Environment

- Python **3.13**
- Poetry **2.x**
- Windows PowerShell examples below; commands can be run from the repository
  root.

Install and start the app:

```powershell
poetry install --with dev
poetry run python run.py
```

Use `poetry run screener-ops --help` to list explicit local operations. The
application entry points are `run.py` (`screener`) and
`src.gates.cli:main` (`screener-ops`).

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `SCREENER_DATA_DIRECTORY` | Root for local SQLite stores and artifacts. | `instance` |
| `SCREENER_HOST` | Waitress bind host. | `127.0.0.1` |
| `SCREENER_SECRET_KEY` | Flask session/signing key. | Local development value; set a private value for shared environments. |
| `MARKET_DATA_KITE_API_KEY` / `MARKET_DATA_KITE_API_SECRET` | Optional shared read-only market-data profile. | Unset |
| `SCREENER_MARKET_DATA_KITE_ACCESS_TOKEN_PATH` | Market-data access token path. | `access_token.txt` |
| `PORTFOLIO_KITE_API_KEY` / `PORTFOLIO_KITE_API_SECRET` | Optional separately configured portfolio profile. | Unset |
| `SCREENER_PORTFOLIO_KITE_ACCESS_TOKEN_PATH` | Portfolio token path. | `portfolio_access_token.txt` |
| `SCREENER_PORTFOLIO_KITE_LIVE_EXECUTION` | Enable live execution controls. | `false` |

For local-only credentials, copy `local_secrets.example.py` to the ignored
`local_secrets.py` and keep the real values out of Git. Never add tokens to
tests, browser storage, job payloads, docs, or logs. Market-data credentials are
not used as a fallback for portfolio credentials.

## Code organization

Read the [architecture overview](architecture.md) before moving code.
Put calculations and domain invariants in `src/domains/`, multi-owner
coordination in `src/gates/workflows/`, HTTP adaptation in `src/gates/http/`,
and shared contracts in `src/platform_kernel/`. Keep browser code as a view and
command client; keep persistence behind owner repositories.

## Useful commands

```powershell
poetry run ruff check src tests run.py tools
poetry run ruff format --check src tests run.py tools
poetry run mypy src run.py
poetry run bandit -q -r src run.py
poetry run python -m pytest -q
```

`make test`, `make lint`, `make type`, and `make security` wrap the corresponding
checks.

## Local data and backups

Do not remove or reset `instance/`, `data/`, `database-archive/`,
`backtesting_results/`, or SQLite sidecars as part of source cleanup. These may
contain user state, archived databases, market reference data, or reproducible
outputs. The `.tours/` folder contains CodeTour walkthroughs and is tracked
documentation. `.venv/`, `__pycache__/`, `.ruff_cache/`, `.pytest_cache/`, and
`.coverage` are environment or generated check artifacts; they can be recreated
and should stay untracked. Use the supported backup/restore commands for active
database files:

```powershell
poetry run screener-ops backup-sqlite instance/stock_screener.db backups/stock_screener.db
poetry run screener-ops check-sqlite instance/stock_screener.db
```

Review restore destinations before running `restore-sqlite`. Keep backups
outside the repository when they contain account or market data.

## Change checklist

1. Identify the owning layer and existing API/data contract.
2. Preserve account, artifact, job, and execution boundaries.
3. Add or update focused tests for behavior changes.
4. Run relevant tests and static checks; record what was actually run.
5. Update operator docs when a workflow or visible behavior changes.
6. Inspect `git diff` for generated data, secrets, and unrelated edits.
