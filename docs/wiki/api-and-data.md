# API and data model

## API conventions

The browser uses JSON APIs under `/api/v2`. Read requests return a bounded
read model. Commands validate their whole payload and return an error object on
failure; callers must use HTTP status plus `error`, not a truthy body alone.

## Main ownership boundaries

| Area | Owner | Key state |
|---|---|---|
| Market/reference | market repository | instruments, bars, snapshots, quality events, index quotes |
| Research | research services/artifacts | features, scores, rankings, lineage |
| Operations | job store/worker | jobs, leases, events, progress, failures |
| Portfolio | ledger | accounts, lots, fills, transfers, valuations |
| Execution | action/broker services | proposals, decisions, guard outcomes, broker intents |
| Strategy | definition/runtime services | versioned YAML-derived definitions and revisions |

## SSE transports

Portfolio ticker and intraday/job transports use server-sent events rather than
a browser WebSocket contract. Connect explicitly, close on account/page change,
and ignore late responses belonging to a prior account context.

## Index data

`GET /api/v2/market/indices/quotes` returns cached quote readbacks with
freshness. `GET /api/v2/market/indices/history?sessions=30` returns a bounded
history suitable for a sparkline; it is not an unbounded tick archive.

## Data integrity principles

1. Published artifacts are immutable and carry manifest/lineage evidence.
2. A universe snapshot is immutable; same-day reuse is valid.
3. Market-history revisions invalidate derived indicator cache entries.
4. Ledger mutations require idempotency and optimistic concurrency.
5. Broker intent, broker receipt and verified fill are separate facts.
