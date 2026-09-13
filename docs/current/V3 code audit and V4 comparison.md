# V3 code audit and V4 comparison

Audit date: 12 September 2026. Source of truth for this report is the code in
the `dead-code-cleanup` worktree at `dabff59`, not its documentation. The scan
covered all thirteen v3 route modules, their service/repository calls, v3 models,
`templates/dashboard.html`, `static/js/dashboard.js`,
`static/js/index_ticker.js`, and the current v4 `run.py` plus every v4
application route/service/UI file.

`Implemented` means an equivalent v4 behavior has a durable service and a
callable route/job. `Changed intentionally` means the v3 operation is unsafe
and v4 deliberately uses immutable/artifact or ledger semantics. `Missing`
means a user-visible or operational behavior has no equivalent yet.

## Code-derived backend comparison

| V3 code surface | What the code does | V4 comparison | Audit result |
|---|---|---|---|
| `init`, `instruments` | Bulk instrument CRUD, full delete, token lookup/update, token-change cascade | Dated Kite NSE/BSE sync and bounded reference query | Changed intentionally; token lookup by provider token, reconciliation report, and explicit token-change audit are missing |
| `marketdata` | Bulk insert/delete, latest/max-date, per-symbol/date and all-symbol range queries, latest/historical all-symbol updates | Immutable Kite/v3 import jobs and bounded symbol bar query | Changed intentionally for writes; coverage/latest-date/all-symbol query and scheduled all-symbol refresh are missing |
| `indicators` | Query/latest/max/all-symbol, individual delete, full calculation and named-column patch | Daily feature artifacts only | Missing direct feature query by symbol/date, latest/coverage query, and controlled indicator patch/revision job |
| `percentile`, `score` | Single-date generation, historical backfill/recalculate and date/symbol queries | Daily calculation publishes percentiles and scores as artifacts | Missing date/symbol read models and a replacement-based range recalculation command |
| `ranking` | Incremental/recalculate, top N, symbol lookup including close price, date query | Dated top-N ranking API and artifacts | Missing symbol ranking/history/close read model and explicit range recalculation; exact tie/candidate parity remains open |
| `app` | One HTTP request synchronously runs pipeline; destructive cleanup/recalculate; SSE log stream | Durable research pipeline with daily child jobs and Friday rank release; job events | Partially implemented; market/reference stages, date-range resume, stage retry/cancel propagation and browser progress stream are missing. Destructive cleanup is intentionally not copied |
| `index` | Global in-process 30-second poll thread, start/stop and cache read | Persisted quote snapshots and freshness-labelled read API | Missing durable poller start/stop/lease command. The v3 global thread is intentionally not copied |
| `config` | Mutable named config GET/POST/PUT | Immutable strategy revision create/list/approve/effective-date API | Changed intentionally; v3 named-config import/alias and research-job config selection are missing |
| `actions` | Generate with daily-stop/midweek/pyramid flags; dates/list; per-action unit/price/status edit; bulk approve/reject; sell-before-buy and open-price cash re-sizing; process | Immutable paper proposal, individual approve/reject/process, ledger events | Missing action calendar/list by date, per-decision amendment revision, bulk operation, pyramid switch, midweek close-stop/vacancy proposal, 5% stale-buy guard, cash-constrained pending state and trailing-stop state |
| `investment` | Dated holdings/summary, manual buy/sell **pending action intents**, capital events, price sync, summary history, FIFO journal, live WebSocket ticker | Paper account, direct manual fills, FIFO cash/realised P&L/events, guarded snapshot import | Missing reviewable manual action intents, cash-transfer events, dated valuation/history, trade journal API, price sync/valuation, live ticker/poller, XIRR and stop-based portfolio/capital risk metrics |
| `backtest` | Long-period run; daily stops, midweek buys and pyramids; rich response/report/history/detail/delete | Bounded paper replay, immutable v4 report list/detail with total return and max drawdown | Missing long-history run policy, stop/midweek/pyramid modes, annual returns, CAGR/XIRR/Sharpe/Sortino/Calmar/trade statistics, trade log/open-position treatment, read-only access to saved v3 histories and UI. Delete is intentionally replaced by immutable retained reports |
| root pages | `/`, `/backtest`, `/actions` render/redirect dashboard pages | `/` redirects to `/app`; Kite callback compatibility exists | `/backtest` and `/actions` navigable page routes are missing |

## Code-derived frontend comparison

The v3 dashboard is a five-tab application. Its JavaScript calls 31 distinct
v1 API paths. V4 has one minimal inline `/app` page with rankings, index quote
readback, job lookup, account lookup and action-proposal review.

| V3 dashboard capability found in code | V4 UI state |
|---|---|
| Pipeline step selector, instrument sync, destructive cleanup, SSE console | Missing; pipeline exists as API/job status only |
| Portfolio summary cards, equity/drawdown charts, holdings table, live P&L chart | Missing |
| Manual buy/sell and capital-event forms | Direct paper-fill API exists; reviewable manual action intent, forms and capital-event API are missing |
| Trade journal table | Missing |
| Top-ranking panel in portfolio tab | Partially present as standalone ranking table |
| Action-date picker, generate action control, action table, per-action edit modal, bulk approve/reject/process | Partially present: proposal list/detail/individual review only |
| Configuration selector/editor | Missing; configuration API has no UI |
| Backtest form, result charts/tables/raw report, run history/detail/delete | Missing; read-only run API exists |
| Index ticker bar with automatic start/poll | Missing; cached quote table exists |
| Live clock, dark terminal styling, DataTables filtering/sorting | Missing; visual redesign was intentionally deferred |

## New gaps added by this audit

The following were not stated precisely enough in the prior pending plan and
are now mandatory migration items:

1. Symbol/date feature, score and ranking read models, including ranking close
   price and market-data coverage/latest-date summaries.
2. A non-destructive range recalculation command that creates replacements and
   links supersession rather than deleting derived data.
3. Action dates, proposal calendar/listing and an amendment-revision model for
   units, execution prices and reasons.
4. Capital transfer events, valuation snapshots, portfolio history and FIFO
   trade-journal projection.
5. Durable index and portfolio quote pollers with explicit local process/lease
   control instead of v3 web-process background threads.
6. V4 pages or routes for `/actions` and `/backtest`, then minimal controls for
   pipeline, portfolio, configuration and backtest readback.
7. Legacy named-config import/alias and active config selection by research
   jobs.
8. Reviewable operator-created manual BUY/SELL intents, distinct from
   recording an already completed direct paper fill.
9. Exact approval and midweek decision rules: sell proceeds before buys,
   open-price re-sizing, cash-constrained pending buys, vacancy advance and
   the 5% stale-buy guard.
10. Dated XIRR and stop-based risk figures, plus the named v3 backtest metrics,
    annual returns and open-position/trade-log readback.

The archived v3 `Pending items.md` is a separate future-work list written
before the v3 portfolio ticker was added. Its 19 entries are now carried
forward in the [current pending list](Pending%20items.md), with implemented-v3
ticker parity tracked above and broader future enhancements separated.

## V3 defects not to reproduce

The scan also found code that is not a migration target: mutable bulk deletes,
in-process global poller state, synchronous provider work in requests,
unversioned configuration updates, and destructive backtest deletion. The v3
`/actions` page route calls `render_template("actions.html")`, but no matching
template exists in the scanned worktree; it is a broken route, not a missing
v4 feature.

## Updated conclusion

The earlier claim that all v3 functionality had been either implemented or
explicitly planned was too broad. Core route families were planned, but the
ten route/UI-level gap groups above were not sufficiently enumerated. They
are now code-derived and must remain open until an implementation and
end-to-end readback close each acceptance criterion.
