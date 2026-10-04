# Live prices — pending phase integration

**Pending per user instruction.** Resume only as required by the defined phase
tasks. WebSocket subscriptions must contain only stocks requiring an action.
Historical bars are added through the separate pipeline; the WebSocket flow has
no session-end historical ingestion step. The existing implementation described
below does not yet enforce action-only subscriptions and is not a completed
execution workflow.


The live stream uses the explicitly bound broker account and its validated Kite
session. It is read-only. Starting it does not arm broker execution or submit an
order. Credentials remain on the server.

Start a connection with `POST /api/market/intraday/live-stream`:

```json
{"action":"start","account_id":"YOUR_LEDGER_ACCOUNT","instrument_ids":["YOUR_PERSISTENT_NSE_INSTRUMENT_ID"]}
```

Use persistent instrument identities from the reference catalog. The service
checks NSE identities, positive unique provider tokens and the selected account
binding before subscribing. Stop with the same route and `{"action":"stop"}`.
One connection is supported per application process; stop it before selecting a
different account or subscription set. A process restart requires an explicit
new start. The durable lease alone does not open a connection.

Read (or periodically ping) the latest quote with:

`GET /api/market/intraday/quotes?account_id=YOUR_LEDGER_ACCOUNT&instrument_id=YOUR_PERSISTENT_NSE_INSTRUMENT_ID`

The response carries LTP, exchange timestamp, receipt timestamp, source, age and
freshness. The read does not call the broker or refresh the exchange timestamp.
An idle socket heartbeat is not a new price. Full tick mode supplies exchange
timestamps. An observation without one remains displayable but is ineligible
for execution checks. `LiveQuotes.execution_quote` also rejects missing, stale,
previous-session and clock-skewed observations. The reader defaults to 60 seconds;
`max_age_seconds` can be explicitly supplied from 1 to 300. This is a quote-reader
setting, not yet a confirmed order execution policy.

Quotes survive process restarts and are isolated by ledger account. Older
timestamps cannot replace a newer quote. Invalid batches do not partially write.
Late callbacks after stop cannot restart the lease or change cached prices.
Existing intraday stop-alert evaluation receives the quotes separately; a missing
risk projection cannot discard the live quote. It still creates no ledger fill.

Historical OHLCV addition belongs to the pipeline and is handled separately.
Live ticks are never converted into historical daily bars. Broker trade
reconciliation remains the source of actual execution prices. Execution integration
and action-only subscription enforcement are pending within the original phase
scope; the prior sizing/timing questions are deferred.

Verified with fake broker sessions and a fake WebSocket ticker. No live connection
or order was opened during this implementation review. Full suite: 360 tests pass.
