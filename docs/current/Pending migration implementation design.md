# Pending migration implementation design

This is the actionable complement to the feature migration ledger. It records
what v3 actually did, the smaller durable v4 replacement, and the acceptance
evidence required before a row can be closed. It deliberately does not copy
v3's global threads, in-place deletes, or provider fallbacks that made results
non-reproducible.

## 1. Daily pipeline and recalculation

Status: the first durable slice is implemented. `POST /api/v2/pipelines/research`
creates a parent record plus ordered daily child jobs. Its advance job releases
Friday ranking jobs only after every selected daily stage succeeds, and
`GET /api/v2/pipelines/research/<pipeline-id>` returns durable parent/stage
status. The remaining work in this section is market/reference orchestration,
calendar ranges, explicit stage retry and cancellation propagation.

V3 route: `/api/v1/app/run-pipeline` ran authentication, instruments, market
data, indicators, percentiles, scores and rankings in one request. It stopped
after a failure, while `/recalculate` deleted downstream tables in place and
rebuilt them. Server-sent logs were the only progress record.

V4 design: create a durable parent pipeline record with ordered child jobs:
reference sync, market fetch, each strategy's daily calculation, and weekly
ranking when applicable. Every child keeps the input fingerprint and its job
ID. The parent derives progress from child job state, permits retry only for
the failed stage, and never deletes published artifacts. A recalculation
creates replacement artifacts and supersedes prior projections.

Acceptance: an interrupted ten-session run resumes from its first unfinished
stage, produces one queryable parent status document, and does not recompute or
overwrite a completed artifact.

## 2. Continuous index quotes

V3 route: `/api/v1/index/start` spawned a process-local daemon which polled
Kite every 30 seconds; `/stop` changed a global flag. It lost state on restart
and could duplicate threads under multiple WSGI workers.

V4 design: run a dedicated local poller command with an operator-owned lease
row (`poller_name`, interval, last_success, last_error, enabled). It submits
the existing `market.fetch-kite-index-quotes` job at most once per interval.
The quote API continues to label cached records FRESH, STALE or CLOCK_SKEW.
Start/stop update durable intent, never create web-process threads.

Acceptance: restart does not create a duplicate poller; disabled polling makes
no provider calls; quote freshness becomes STALE after the configured window.

## 3. Corporate actions and adjusted bars

V3 behavior: prices were largely unadjusted and manual repair was possible,
but neither an action source nor dependent recalculation was durable.

V4 design: ingest split/dividend facts as immutable source artifacts keyed by
instrument and effective date. Publish a new adjusted-bar revision rather than
mutating `market_bars`; link affected feature, score, ranking, action and
backtest artifacts through catalog invalidation. Keep unadjusted Kite bars as
the raw execution basis and expose adjustment basis on every read.

Acceptance: a synthetic split produces a distinct adjusted series, qualifies
only dependent artifacts, and leaves the raw source and prior reports readable.

## 4. Strategy parity and approved configuration use

V3 behavior: configuration rows were mutable at runtime; Strategy 1 used an
ordering-dependent cross-sectional bandwidth change, and Strategy 2 carried a
constant-zero quality field plus a relative-volume field mislabeled as turnover.

V4 design: strategy configuration revisions already have draft/approval/
effective-date lifecycle. Next, research jobs resolve the active revision and
include its artifact in daily feature/score lineage. Preserve a legacy formula
mode only for comparison; make corrected formulas the default after a recorded
parity decision. Rename Strategy 2's relative-volume field in output while
retaining a compatibility alias.

Acceptance: for a frozen universe/date, reports show exact inputs, revision ID,
tie policy and factor deltas versus v3; strategy outputs cannot be silently
changed by configuration edits.

## 5. Action lifecycle parity

V3 behavior: generated pending BUY/SELL/SWAP actions, allowed per-item edits,
optional pyramid adds, close-based midweek stops, then updated current price
and trailing stop when processing approved actions.

V4 design: retain the existing immutable paper proposal and ledger fills. Add
a versioned position-risk projection keyed by account/instrument: entry stop,
current trailing stop, score and source action revision. A midweek close check
generates a separate next-open SELL proposal; it never inserts a fill directly.
Manual changes create a new proposal revision with explicit operator reason,
never mutate an approved artifact.

The code comparison also requires the v3 execution rules to be recorded as
policy, not lost inside a generic "action parity" item: approve SELLs before
BUYs; re-size BUYs at the actual open within the available cash budget; keep
zero-unit, cash-constrained BUYs pending; optionally advance ranked pending
BUYs when a midweek stop creates a vacancy; and skip that advance when the
candidate's close is more than 5% above its signal close. V4 should make the
threshold and timing explicit in a versioned policy and emit a reason for
each skipped or deferred decision. The shared portfolio engine has a pyramid
decision type, but the current paper-proposal job does not expose the v3
operator switch or its half-size add policy.

Acceptance: stop breach, manual rejection, retry and partial execution all
produce auditable events; the same candidate data yields a side-by-side v3/v4
decision comparison.

## 6. Portfolio valuation and journal

V3 behavior: `investment_holdings`, summary rows and capital events mixed
cash, value, risk and realised gain in mutable projections.

V4 design: keep the append-only fill ledger as source of truth. Add explicit
cash-transfer events, a dated valuation snapshot from market bars/quotes, and
a journal entry projection. Import uses only a v3 snapshot because v3 lacks a
complete sale-event history; it must remain `PARTIAL` quality.

The dated summary read model must include the v3 user-facing cash, invested
capital, realised and unrealised gain, stop-based portfolio/capital risk, and
cash-flow-aware XIRR figures, each with its calculation basis. V4 currently
exposes cash, open FIFO lots and realised P&L, but cannot reproduce the v3
summary/history or the dashboard's equity and drawdown views.

Acceptance: a projection rebuild equals the stored account view, valuation
identifies stale prices, and imported accounts disclose unavailable historical
realised P&L.

## 7. Backtest parity

V3 behavior: supported long periods, optional daily stop checks and midweek
buys, and wrote text reports. Its data and execution assumptions were not fully
versioned.

V4 design: extend the shared portfolio engine with the versioned stop-risk
projection and corporate-action basis. Parameterize calendar, fees, slippage,
entry timing and strategy/config revision; publish trade ledger, equity curve,
drawdown, turnover and diagnostics as one immutable report.

Match the useful v3 report readback explicitly: CAGR, XIRR, Sharpe, Sortino,
Calmar, win rate, profit factor, expectancy, average holding period,
year-by-year returns, trade log, buy/sell/pyramid counts and end-of-run open
positions with unrealised P&L. Record whether those positions are marked to
market or force-closed. V4's current report only calculates total return and
maximum drawdown, so "richer metrics" is still an open migration item.

V3 also saved run metadata in `BacktestRunModel` and the summary, equity
curve, trades and text report under `backtest_history/<timestamp>_<id>`.
Current v4 run-list/detail APIs only know v4 cataloged runs. Add a read-only,
digest-checked legacy history import or archive view so existing v3 reports
remain discoverable, clearly labelled as legacy and not represented as v4
replays. The v3 delete operation is not needed.

Acceptance: a frozen historical period has a documented v3/v4 trade diff; no
future bar, post-period quote or mutable configuration is reachable by a run.

## 8. Reference and market-data reconciliation

Status: bounded `GET /api/v2/market/coverage` returns paginated
per-instrument bar counts, earliest/latest dates and the latest source
artifact's catalog quality/status, including instruments with no bars.
`GET /api/v2/reference/tokens/<token>` resolves dated token assignments
and flags ambiguity; `/instruments/<id>/token-history` audits observed token
changes. The assignment response labels the symbol as current because past
symbols are not yet stored with token observations. Daily reconciliation and
scheduled all-symbol refresh remain pending.

V3 behavior: used static NSE/BSE files, Kite instruments and provider fallbacks
without a durable reconciliation report.

V4 design: publish a daily reconciliation artifact for source count, matched
ISINs, duplicate symbols, exchange fallback, excluded/expired tokens and bar
coverage. The scheduler uses that artifact to choose only active identities.

Acceptance: each daily market run names every excluded or unmatched symbol and
never silently switches an instrument identity.

## 9. Read models and minimal replacement pages

Code-audit addition: v3 exposed symbol/date lookups for market bars,
indicators, scores and rankings, plus dated holdings/summary history. Its
dashboard used those responses for portfolio, action and backtest screens.

V4 design: add bounded, indexed read models rather than exposing artifact
files or mutable tables directly. They must return the source artifact ID,
quality and date/revision with every result. Add route-level `/actions` and
`/backtest` pages that use these v4 APIs, then add compact controls for
pipeline status, configuration revision selection, valuation/journal and
backtest report readback. The v3 visual system and third-party CDN widgets are
not required for parity; the workflow and data must be available.

Acceptance: every non-destructive v3 dashboard request has a v4 replacement,
and a browser run can inspect a ranking, account, action proposal, valuation
and backtest without manual JSON URLs.

## 10. Amendments, cash transfers and valuation

Code-audit addition: v3 supported per-action unit/price/status updates and
capital infusion/withdrawal records. V4 supports manual fills but has neither
an amendment revision nor explicit cash-transfer events.

V4 design: action edits create a replacement proposal decision revision with
operator reason and immutable lineage. Cash transfers become versioned ledger
commands, and valuation snapshots price open lots using an explicit dated bar
or live quote source. The journal pairs ledger fills FIFO without modifying
history.

Acceptance: amend, deposit, withdraw, valuation and journal calls are
idempotent, replayable and visible through both API and minimal UI.

Manual trading is a separate missing workflow. In v3,
`/investment/manual/buy` accepted a batch of symbol/date/units/price/reason
entries, checked prior-session bars and available capital, then inserted
reviewable pending BUY actions with the same sizing/ATR fields as generated
actions. `/investment/manual/sell` created a pending SELL for a held symbol.
V4's `/portfolio/accounts/<account_id>/fills` records completed paper fills
directly; it is not a manual action-intent replacement. Add operator-created
manual proposal intents (including batch BUY and partial SELL), validation,
review/amend/reject/process readback and source/reason lineage. Keep the
existing direct-fill command for recording an already executed paper trade.

Acceptance: a manual BUY that exceeds cash or lacks the required prior bar is
rejected with a per-symbol reason; a valid manual BUY/SELL appears in the
proposal calendar and can be processed once; creating the intent alone does
not change holdings or cash.

## 11. Gated Kite execution and broker reconciliation

Status: deliberately pending. V4 currently supports only paper orders and
manual paper fills. The isolated `PORTFOLIO_KITE_*` profile and daily token
path are in place, but no code is permitted to submit a live broker order yet.

V4 design: introduce a `BrokerExecutionGateway` behind the existing execution
port, with a `KiteExecutionGateway` selected only by an explicit,
disabled-by-default live-execution feature gate. A submitted order creates an
immutable local command first (account, proposal decision, idempotency key,
requested instrument, side, quantity and order type). It then records the Kite
order ID, raw broker state and timestamps as append-only execution events. A
durable, operator-visible reconciliation job fetches only submitted/open order
IDs, maps broker states without collapsing partial fills, and posts each newly
confirmed fill to the FIFO ledger exactly once using the broker trade/fill ID
as the idempotency key. Rejections, cancellations, expiries and modifications
remain execution events and never create holdings.

Manual fallback: the operator may record a manual fill price/quantity only
against a pending local order, with a required reason and source. It must be
clearly marked `MANUAL`, never overwrite broker evidence, and be refused once
the same broker fill has been posted. The reconciliation screen must surface
price/quantity/state conflicts for operator resolution rather than silently
altering the portfolio.

Security and rollout: broker credentials stay per deployment/user in the
portfolio profile and must never fall back to the shared market-data profile.
Before enabling the feature, add authenticated user ownership (or a separate
single-operator deployment boundary), encrypted secret storage for a shared
server, confirmation/re-authentication for live submissions, allowlisted
accounts/instruments, rate limits, audit logs, a kill switch, and recovery
tests for duplicate callbacks, timeout-after-submit, partial fills and process
restart. Start in read-only order-status reconciliation and a broker sandbox;
enable live placement only after an explicit production rollout decision.

Acceptance: an integration sandbox run proves that a submit timeout followed
by retry creates at most one broker order, partial fills update holdings/cash
once per broker fill, manual and broker fills cannot double-post, and the
portfolio can be rebuilt solely from immutable execution and ledger events.

## Delivery order

1. Complete durable daily pipeline with market/reference stages, resume and
   cancellation; add bounded research/market read models.
2. Index poller command and reconciliation report.
3. Action amendments, cash transfers, valuation/journal, then position-risk
   projection and midweek stops.
4. Corporate actions and adjusted revisions.
5. Research/config parity decision, named-config import and Strategy 2 semantic cleanup.
6. Long-history parity backtests and final dashboard expansion.
7. Read-only broker reconciliation, sandbox execution, then a separately approved
   live-order rollout.

Each implementation must add a migration, protected API/CLI surface,
representative end-to-end run and a readback check before its ledger row is
marked complete.
