# System workflows

## Day-zero workflow

The day-zero build establishes the fixed current universe and then creates the
historical dataset used by both strategies.

```text
Kite NSE instruments ----+
                         +--> ISIN deduplication --> YFinance market cap
Kite/BSE reference ------+                              |
                                                        v
                                              atomic universe publish
                                                        |
                                                        v
Kite historical API --> bounded symbol jobs --> bars + coverage windows
                                                        |
                                                        v
                                  daily features/scores --> weekly rankings
                                                        |
                                                        v
                                                  backtests
```

1. Run `reference.enrich-day0-universe`.
2. NSE and BSE instruments are synchronized and deduplicated by ISIN; NSE wins
   when both listings exist.
3. YFinance tries `<symbol>.NS` for NSE. BSE tries `<symbol>.BO`, then
   `<security-code>.BO`, with a delay between attempts.
4. Stocks strictly above the configured threshold, normally ₹500 crore, form
   the initial membership.
5. Membership and completion metadata are committed atomically.
6. Schedule historical Kite bars from `2015-01-01` through the latest completed
   market date in ranges of at most 365 days.
7. Run research across completed sessions, followed by weekly rankings.
8. Validate coverage and representative numerical outputs before trusting a
   backtest.

The current active database may contain inactive raw membership from an
interrupted older build. A successful day-zero job replaces it.

## Recurring universe workflow

Later universe runs do not re-filter existing members out. They:

- retain every completed-universe member regardless of current market cap;
- update available market-cap metadata;
- retain an existing member when enrichment is unresolved; and
- add a new stock once its observed cap exceeds the threshold.

Unexpected code failures abort the job. The previously completed universe
remains active until the replacement transaction succeeds.

## Market-data journey

`POST /api/v2/market/refresh` calls `MarketRefreshPlanner.schedule()`.

The planner selects:

1. all active fixed-universe members;
2. every instrument held in any open portfolio account; and
3. the NIFTY 500 benchmark.

It does not apply price, turnover, circuit, current market-cap, or strategy
eligibility filters. A held stock remains scheduled even when delisted from a
screen or blocked at upper/lower circuit. Missing identities and provider
tokens are reported rather than silently dropped.

The planner creates one `market.fetch-kite-bars` job per missing bounded range.
The handler:

1. validates instrument and date range;
2. checks explicit provider coverage;
3. requests Kite historical data;
4. normalizes and validates OHLCV rows;
5. publishes a source artifact when rows exist;
6. upserts bars; and
7. records the successfully requested range, even when Kite returns no rows.

This makes retries idempotent and lets pre-listing periods complete normally.

## Index quote journey

During NSE market hours, `BackgroundIndexPoller` periodically submits
`market.fetch-kite-index-quotes`. Polling state and the latest job ID are
durable. The handler publishes a quote artifact and upserts the latest index
projection. UI refresh behavior is separate and remains a pending aesthetic
improvement.

## Research journey

`POST /api/v2/pipelines/research` creates a fingerprinted pipeline. With
`orchestrate_data=false`, daily jobs are queued immediately. With
`orchestrate_data=true`, reference sync, market refresh, and reconciliation
must complete before daily research starts.

For each strategy and session, `ResearchJobs.calculate_day()`:

1. loads the active immutable strategy revision;
2. reads up to 900 calendar days of histories;
3. separates benchmark history when required;
4. executes the registered instrument feature implementation;
5. optionally performs cross-sectional calculation;
6. applies configured factor weights and modifiers;
7. publishes revision-aware output artifacts; and
8. replaces the daily score projection for that revision/date.

After all daily stages succeed, the coordinator finds each week's last
submitted session and queues `research.rank-week`. Ranking uses available
daily scores, aggregates according to the strategy definition, and stores a
deterministic ranking artifact and relational projection.

If a stage fails, the pipeline is failed and that stage can be retried without
discarding completed siblings. Cancellation requests propagate to child jobs.

## Strategy revision journey

YAML enters through startup seeding or `POST /api/v2/strategies`. The definition
service parses and validates it, canonicalizes it to stable JSON, hashes it,
and stores an immutable `VALIDATED` revision. Activation retires the previous
active revision. New research and backtests use the new revision; historical
artifacts continue referencing the exact old revision.

Today, runtime calculation still selects a registered custom implementation
from the revision's `calculation` section. See
[Adding a strategy](adding-a-strategy.md) for the current process and limitation.

## Backtest journey

A `backtest.run` durable job receives strategy, date range, capital, and
pyramiding settings. It loads revision-aware rankings and bars, replays the
portfolio chronologically, applies corporate-action-adjusted data where
configured, and publishes a report artifact.

The report distinguishes total return from CAGR and includes annual returns,
XIRR, maximum drawdown, Sharpe, Sortino, Calmar, fills, orders, attribution
inputs, and the equity curve. Backtest orders and fills remain inside the
simulation and never call `Ledger.record_fills()`.

No hardcoded stock eligibility check is applied during replay. If a stock has
the required historical ranking and tradable bar, it can participate.

## Portfolio journey

An account starts with opening cash. Actual transactions arrive through the
manual fill API or through broker-order reconciliation. Each command supplies
an idempotency key and expected ledger version.

`Ledger.record_fills()` validates the entire batch, enforces holdings and cash
constraints, appends immutable events, and advances the account version.
Projection replay derives cash, FIFO lots, realized P&L, and holdings.

Strategy actions follow a separate path:

```text
prior ranking + current ledger + market bar
                    |
                    v
             action proposal
                    |
             review / amendment
                    |
          execution intent or manual confirmation
                    |
             confirmed execution
                    |
                    v
                 ledger
```

Generated strategy and stop proposals stop before the ledger. A manually
confirmed transaction proposal can be approved and processed. Broker intents
are dispatched only when live execution is configured and armed; reconciliation
posts confirmed fills idempotently.

## Portfolio valuation journey

Portfolio views replay ledger events and match holdings to the latest available
market bars. A persisted dated valuation is checksum protected and supports
summary, valuation-history, ticker, XIRR, and journal views. Missing fresh
prices are marked stale rather than silently treated as current.
