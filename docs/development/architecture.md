# System architecture

Stock Screener is a local-first Python application composed as a modular
monolith. Flask is the HTTP adapter; Waitress serves it. SQLite-backed stores
hold durable market, reference, research, operation, portfolio, and artifact
state. The app does not depend on a separate database server.

## Repository ownership

| Path | Responsibility |
|---|---|
| `src/platform_kernel/` | Shared value types, validation errors, artifact contracts, SQLite helpers, and security redaction. |
| `src/domains/` | Domain rules and owner repositories for market data, reference data, strategies, research, operations, accounting, execution, and backtesting. |
| `src/gates/workflows/` | Use cases that coordinate multiple domain owners, such as market refresh, research, pipeline, action generation, broker orders, and portfolio sync. |
| `src/gates/http/` | JSON and SSE adapters. They validate requests and call workflow/domain services. |
| `src/gates/app.py` | Composition root, Flask factory, route registration, worker lifecycle, and local server startup. |
| `templates/`, `static/` | Server-rendered page shell and browser behavior. Browser code calls the HTTP API; it does not own durable business state. |
| `strategies/` | Versioned active strategy definitions loaded by the strategy registry. |
| `tests/` | Focused domain and gate tests that mirror the current source ownership. |

The intended dependency direction is **HTTP → workflows → domain owners →
platform kernel**. Domains should not import HTTP adapters or other domain
internals. Cross-domain coordination belongs in workflows or the composition
root. The code and focused tests are the source of truth for current behavior.

## Runtime composition

`run.py` preserves the stable launcher. `src.gates.app.create_app()` reads
`RuntimeConfig`, resolves the local data directory, constructs repositories and
workflows through `ApplicationServices`, and registers HTTP blueprints. The
local server binds to `127.0.0.1:5000` unless `SCREENER_HOST` is configured.

The background worker processes durable jobs from the same local operations
store. A queued job does not run merely because it is visible in a page. The
worker status API reports execution state; pipeline rows report job-stage state.

## Data flows

```text
NSE/reference providers
        │
        ▼
immutable snapshots + normalized market bars ──► quality/coverage checks
        │                                               │
        └──────────────────┬────────────────────────────┘
                           ▼
                   strategy calculations
                 ┌─────────┴──────────┐
                 ▼                    ▼
      weekly Momentum rankings   daily Positional Trend signals
                 └─────────┬──────────┘
                           ▼
                 immutable research artifacts
                           │
                           ▼
                reviewable action proposals
                           │ approval / separate broker workflow
                           ▼
                verified execution and ledger events
```

Backtests use the same dated data and strategy definitions in isolated
simulation. They write saved reports, not portfolio fills.

## Persistence and trust boundaries

- Published research and backtest artifacts are immutable and retain lineage.
- Jobs retain status, attempts, leases, results, and event history.
- Portfolio writes use a versioned local ledger; they are separate from broker
  account authentication and market data credentials.
- An action proposal, approval, broker intent, broker receipt, and verified fill
  are distinct records. No earlier record is evidence of a later one.
- Provider credentials and tokens remain in server configuration/files and are
  excluded from the UI, docs, and logs.
- The default data directory is `instance/`; generated reports can also live
  under `backtesting_results/`. Both are runtime/user data, not cleanup targets.

For HTTP contracts see [API and data](../reference/api-and-data.md). For safe local
operations and configuration see [Development](setup.md).
