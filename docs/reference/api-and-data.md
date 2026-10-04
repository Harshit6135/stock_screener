# API and data contracts

The browser API is JSON under `/api`. Read routes return bounded read models.
Command routes validate input and return a non-2xx response with an `error`
message on failure. Clients should use both the HTTP status and response body.

## Route map

| Prefix | Use |
|---|---|
| `/api/portfolio` | Local accounts, fills, transfers, valuation, journals, and risk configuration. |
| `/api/actions` | Proposal readback and decisions, risk projections, manual intents, execution-policy reports. |
| `/api/operations` | Durable jobs, event history, cancellation, and worker controls. |
| `/api/pipelines` | Research pipeline submit, status, stage retry, and cancel. |
| `/api/research` | Features, scores, weekly rankings, artifacts, and research diagnostics. |
| `/api/positional-trend` | Daily signal build jobs and signal readback. |
| `/api/universe` | Immutable universe snapshots, members, differences, and refresh. |
| `/api/market` | Market refresh, bars, coverage, quality events, indices, and live quote readbacks. |
| `/api/reference` | Instruments, tokens, and dated macro, sector, market-cap, and fundamentals artifacts. |
| `/api/strategies` | Active definitions and immutable strategy revisions. |
| `/api/backtests` | Saved backtest, walk-forward, and attribution report readback. |
| `/api/broker-accounts` | Broker account setup, authentication, validation, holdings, and reconciliation. |
| `/api/portfolio` | Broker order intents and order lifecycle, alongside local portfolio operations. |
| `/integrations/kite` and `/api/integrations/kite` | Server-side authorization pages, callbacks, and authorization start for configured Kite profiles. |

The HTTP blueprint modules in `src/gates/http/` are the route source of truth.
Use those modules for exact fields, validation, and status codes.

## Examples

Read proposals for an account and date:

```text
GET /api/actions/proposals?account_id=Harshit&action_date=2026-10-05
```

Find the latest stored session before a target action date:

```text
GET /api/actions/sessions/latest?action_date=2026-10-05
```

Read a durable job:

```text
GET /api/operations/jobs/44
```

Read Momentum rankings:

```text
GET /api/research/ranking-weeks?strategy_id=momentum
GET /api/research/rankings?strategy_id=momentum&week_end=2026-10-01&limit=100
```

## Persistence and consistency

- Artifacts are immutable payloads with manifests, quality, and lineage.
- Job events are durable; poll by job ID or reconnect to the event stream using
  the last event cursor.
- Pipeline stage status is a projection of referenced durable jobs.
- Portfolio commands use an expected ledger version and idempotency key where
  specified. A stale write must be re-read and reviewed.
- Broker intent, submission, receipt, and verified fill are separate facts.

## Streaming

Job events, portfolio ticker, and live market streams use server-sent events.
Close streams when changing account or leaving the page, and ignore responses
from an earlier selection. A heartbeat is not a new market observation.

See [Portfolio and actions](portfolio-and-actions.md) for the proposal lifecycle
and [Operations](operations.md) for worker and job behavior.

Read-only, account-bound streaming details are in the [live prices guide](../user/live-prices.md).
