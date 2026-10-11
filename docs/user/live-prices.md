# Live prices

The optional Kite WebSocket stream supplies read-only live quotes for explicitly
selected instruments. It does not submit orders and does not automatically limit
subscriptions to stocks that need an action. Historical bars are added through the
separate market pipeline; ticks are never converted into daily bars.


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
new start. The stream controller clears its saved enabled/connected state on
startup so Go live can open a new connection. The durable lease alone does not
open a connection.

Read (or periodically ping) the latest quote with:

`GET /api/market/intraday/quotes?account_id=YOUR_LEDGER_ACCOUNT&instrument_id=YOUR_PERSISTENT_NSE_INSTRUMENT_ID`

The response carries LTP, exchange timestamp, receipt timestamp, source, age and
freshness. The read does not call the broker or refresh the exchange timestamp.
Live holding day P&L uses `(LTP - previous close) × held units`. The previous
close comes from the same Kite tick's OHLC data, so gaps in locally stored daily
bars cannot turn a multi-session price move into today's P&L. If the tick lacks a
valid previous close, live day P&L is unavailable. Older bar fallback prices also
leave today's day P&L unavailable. These are current-holding price changes;
realised P&L remains separate.
See the [Kite quote packet fields](https://kite.trade/docs/connect/v3/websocket/#quote-packet-structure).

An idle socket heartbeat is not a new price. Full tick mode supplies exchange
timestamps. An observation without one remains displayable but is ineligible
for execution checks. `LiveQuotes.execution_quote` also rejects missing, stale,
previous-session and clock-skewed observations. The reader defaults to 60 seconds;
`max_age_seconds` can be explicitly supplied from 1 to 300. This is a quote-reader
setting, not an order execution policy.

Quotes survive process restarts and are isolated by ledger account. Older
timestamps cannot replace a newer quote. Invalid batches do not partially write.
Late callbacks after stop cannot restart the lease or change cached prices.
Existing intraday stop-alert evaluation receives the quotes separately; a missing
risk projection cannot discard the live quote. It still creates no ledger fill.
Per-tick alerts evaluate only the hard stop (3% below the weekly trailing stop).
Normal stop sells are decided from completed weekly closes, remain due if the
next week's price recovers, and require explicit sell approval. Live prices and
midweek daily closes do not ratchet the trailing stop.

Historical OHLCV addition belongs to the pipeline and is handled separately.
Live ticks are never converted into historical daily bars. Broker trade
reconciliation remains the source of actual execution prices. The stream requires
a configured and validated account and an explicit list of instrument IDs. One
connection is supported per application process. The lease records the selected
subscription but does not open a connection after restart.

See [API and data contracts](../reference/api-and-data.md) for the route map.
