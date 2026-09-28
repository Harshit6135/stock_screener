# Strategy 4 integration plan

Status: implementation plan, updated 2026-09-28. This plan does not activate Strategy 4 for live orders. Pyramiding is deferred; initial integration supports single entries and exits only.

## Target behavior and boundaries

Implement the v4 positional trend rules as a daily event strategy in the existing application. The current research scripts are the executable reference: `src/application/positional_trend.py`, `tools/strategy4_event_study.py`, and `tools/strategy4_backtest.py`. Keep Strategy 1/2 factor scoring and weekly rebalance behavior intact.

The reference run uses the current Nifty 500 EQ list, ₹5,00,000 initial capital, at most 15 distinct stocks, 1% nominal risk per new order, 10% equity per order, 1% of prior 30-session average traded value per order, and 50 bps modeled round-trip cost. Limits must be configurable. Strategy 4 does **not** inherit Strategy 1/2's factor percentiles, composite score, score exit, swaps, ATR stop, or pyramid fraction. The current Nifty 500 list is broader than only small and mid caps; adding a size filter would be a separately versioned strategy change. Per the agreed research scope, use stored OHLCV without corporate-action adjustment.

On each completed session T, a new 50-session Donchian first-cross with ADX(14) > 25, bullish Supertrend(10, 3), close above Supertrend, and prior-30-session ADTV > ₹10 crore creates a candidate. The next-session stop anchor is `max(Supertrend_T, prior-20-session Donchian lower_T)`. Sell a held stock after `close_T` falls below either Supertrend or the prior-20-session lower band. Exits precede buys. New names share one ranking: ADX descending, ADTV descending, symbol ascending. The first integrated version does not add to existing holdings.

## Existing seams and incompatibilities

| Existing component | Reuse | Required change |
|---|---|---|
| `MarketRepository` and `MarketRefreshPlanner` | NSE identities, OHLCV, refresh jobs, held-name coverage | Add Strategy 4 universe/signal coverage checks and a daily warm-up read path. |
| `StrategyDefinitions` and `StrategyRuntime` | Immutable revisions and strategy catalog | Support a daily event strategy without fabricated factor weights or weekly score fields. |
| `ResearchJobs` and `ResearchPipelineJobs` | Job coordination, artifacts, status | Route Strategy 4 to daily signals/rankings, not factor percentiles and weekly means. |
| `portfolio_engine.evaluate` | Existing Strategy 1/2 behavior stays stable | Its score exits, ATR stops, swaps, add-first priority, and `pyramid_fraction` conflict with Strategy 4. Use a distinct pure Strategy 4 decision function behind a shared proposal/fill interface. |
| `ActionJobs`, `Ledger`, action API | Proposal lifecycle, approval, lot ledger, audit | Add Strategy 4 dispatch, persisted signal/stop/lot evidence, and open-price preflight. |
| `BacktestJobs`, backtest API | Run catalog, artifact publishing, report endpoints | Add a Strategy 4 replay adapter using the same decisions as action generation. The current runner consumes prior **weekly** rankings and Strategy 1 ATR cache. |
| Dashboard | Strategy selector and proposal/replay review | Show Strategy 4 daily signals and its own risk fields; hide weekly rebalance, score exit, and pyramid-fraction controls for this strategy. |

## Task-by-task delivery

### 1. Freeze the versioned rule and execution contract

- Add a Strategy 4 rule/config definition under `strategies/` and a versioned contract in `src/application/positional_trend.py` or a dedicated rules module. Include indicator parameters, strict comparisons, ranking ties, costs, and all configurable limits.
- Resolve the live execution constraint explicitly: the exact next **opening price** and >3% gap check cannot both be known before an unconditional market-on-open order is submitted. Specify a supported open-aware order/preflight path, or a first tradable quote/limit execution model, and make the replay use the corresponding fill assumption. Record the decision in the strategy revision.
- Record that an open above the signal close by **more than** 3% is skipped; equality is allowed. An open at or below the anchor is skipped. Specify how missing next-session bars expire entry intents, while exits wait for a valid executable price.
- **Done when:** one versioned rules document and fixtures define the same outcome for close signal, next-session candidate, skip, fill, exit, and add cases. No execution setting silently falls back to Strategy 1/2 defaults.

### 2. Register Strategy 4 without factor scoring

- Extend `StrategyDefinitions` validation and `StrategyRuntime` to recognize an `event_signal` strategy type with its own `signal_rules`, `ranking`, and `portfolio_policy` schema. Do not insert placeholder factors merely to satisfy the current mandatory `factors` field.
- Seed a `strategy4` immutable revision from `strategies/`, with ₹5 lakh/15 stocks/1% risk as defaults that can be overridden per run or account. Include the code/rule hash in dependent artifacts.
- Register the calculation in `src/indicators/custom/__init__.py` if using the runtime registry.
- **Done when:** Strategy 4 appears in the strategy catalog with a stable revision ID, and existing Strategy 1/2 definitions and activations are unchanged.

### 3. Capture the universe and data evidence

- Add a daily Nifty 500 EQ universe snapshot reader using ISIN identity, CSV/source checksum, observed date, matched and missing instruments, and the market-session calendar. Use current membership for live dates; label retrospective use as survivorship biased in historical reports.
- Support a versioned universe-source choice: `NIFTY500` or `APPLICATION_MCAP500` (the existing ₹500 crore app universe, including NSE and BSE). Record snapshot date, exchanges, threshold, and membership hash. Historical use of a current market-cap snapshot must additionally disclose market-cap look-ahead bias. The 2026-09-19 application snapshot contains 1,851 members; treat its comparison as an experiment, not a historical ₹500 crore eligibility series.
- Read at least 100 valid prior stock bars. Skip absent stock-session records like holidays while preserving indicator history; only malformed stored OHLCV resets warm-up. Capture last completed market date and source bar snapshot IDs.
- Reuse market refresh jobs to include all current constituents and every held name, even if it leaves the current index. Do not silently remove an existing position because membership changed.
- **Done when:** a dated coverage artifact identifies every eligible, missing, and under-warmed stock, and a rerun with the same source snapshots yields the same universe.

### 4. Move indicator computation into the application path

- Make `feature_series` in `src/application/positional_trend.py` the single implementation used by research, action generation, and replay. Compute prior 50 high, prior 20 low, Wilder ADX(14), ATR(10), Supertrend(10, 3), and prior 30 ADTV. Store the completed-session feature values and their input/code hashes in the indicator cache or a Strategy 4 artifact namespace.
- Preserve the prior-bar Donchian windows and the documented Supertrend seed/flip convention. Include `first_cross`, filter decisions, exit flag, ADX, ADTV, Supertrend, lower band, and anchor in each row.
- **Done when:** fixed OHLC fixtures and full-history recomputation match the reference implementation exactly, with no forward data in a session's feature row.

### 5. Publish daily signals and a common candidate ranking

- Add a Strategy 4 daily signal job and indexed read model or cataloged artifact. Publish every signal/exit decision with source feature ID, rule revision, date, instrument, reason codes, and ranking inputs.
- Rank all filtered first-cross candidates once per session by `(-ADX, -ADTV, symbol)`. Include held and unheld names in the same ordered list; eligibility for an add is checked against account lots at execution preflight, not by putting adds ahead of buys.
- Make the job idempotent by completed date, revision, universe snapshot, and source bar IDs. Keep missing or stale data visible rather than carrying a signal forward unnoticed.
- **Done when:** a read endpoint can reproduce the exact candidate order and explain why a stock was included or skipped. Re-running the same job creates no conflicting ranking.

### 6. Build a pure Strategy 4 portfolio decision function

- Add a storage-free evaluator in `src/portfolio_engine/` or a Strategy 4 domain module that accepts prior-close signals, current executable prices, cash/equity, existing lots, and policy. Return ordered `SELL`, `BUY`, and skip decisions with quantities and evidence.
- Execute exit intents first. For each ranked buy/add, apply the gap and anchor checks, then size whole shares as the minimum of `floor(equity × risk_fraction / (open − anchor))`, `floor(equity × order_cap_fraction / open)`, `floor(ADTV × participation_fraction / open)`, and the fee-aware cash limit.
- Do not generate add orders in the initial integration. Count each held ticker once against the stock limit.
- Keep stop/exit state and entry lots explicit. A nominally protected old lot may still lose money after a gap or fees; report this distinction.
- **Done when:** deterministic tests cover competing new/add signals, ties, gaps, zero-size orders, multiple lots, exits before buys, insufficient cash, and the 15-name limit.

### 7. Persist stops, lots, and reviewable action proposals

- Extend the `ActionJobs.generate` dispatch for `strategy4`, using the existing `Ledger` open lots and proposal lifecycle. Persist Strategy 4 stop/risk projections separately from the current ATR projection and tie them to account, signal date, rule revision, and proposal/ledger version.
- Preserve each remaining lot's actual **buy fill price** for the pyramid check. `portfolio_accounting.Lot.unit_cost` includes allocated buy fees, so it cannot be substituted for the agreed fill-price comparison. Reconstruct the FIFO remainder from immutable fills or extend the lot projection with fill identity and raw price.
- Produce a close-time **intent** from completed T data. At T+1 execution preflight, apply the open-aware price/gap rule and recompute units from actual equity and cash. Record exact reasons for every skipped intent; stale intents expire rather than becoming arbitrary later buys.
- Include BUY/add/SELL quantities, signal close, executable price, anchor, risk budget, limit that bound the size, lot evidence, and source snapshot IDs in the proposal artifact. Reuse approve/reject/amend/process paths with ledger-version checks and idempotent fills. Keep broker execution disabled until the execution contract from Task 1 is verified.
- **Done when:** proposal creation and replay of the same inputs produce identical decisions; processing once updates the ledger once; restart/retry does not duplicate fills.

### 8. Route Strategy 4 through jobs and APIs

- Register daily indicator, signal, and action jobs in `ApplicationServices.create` and coordinate data refresh → completed-bar validation → feature build → signal publication → account proposal. Keep the Strategy 1/2 weekly pipeline path unchanged.
- Add Strategy 4 daily signal/ranking read endpoints and use the existing jobs and action proposal endpoints where their payload contracts fit. Extend contracts where `ranking_week_end` currently assumes a weekly date; expose `signal_date` for Strategy 4.
- **Done when:** one completed exchange session can be processed end to end through the worker, with job status, artifact lineage, and an account proposal visible through APIs.

### 9. Integrate the shared decision path into backtesting

- Add a Strategy 4 branch/adapter in `BacktestJobs` that replays published daily signals through the **same evaluator** and execution contract as Tasks 6–7. Store a normal run artifact and index row so `/api/v2/backtests/runs` can read it.
- Persist policy revision, universe checksum, market-bar snapshot IDs, feature/signal hashes, fill model, fees, skip counts, lots, open holdings, equity curve, annual returns, drawdown, and the last stored session. Mark open positions to market; do not silently force a final liquidation.
- Compare parity with the standalone reference for the 2022-01-01 to 2026-09-18 run at ₹5 lakh, 15 names, 1% risk, and pyramiding disabled. Any difference from a changed executable-price model must be explained and versioned, not hidden in rounding.
- **Done when:** same inputs yield identical signal order, fills, cash, and equity within an explicit rounding tolerance, and a published run is readable in the existing backtest API.

### 10. Add Strategy 4 controls and explanations to the UI

- In the dashboard, show the Strategy 4 signal date, Donchian/ADX/Supertrend/ADTV values, entry/add/exit reason, pending next-session status, and per-order risk/participation limits.
- Show its configurable capital, stock count, risk %, order cap, ADTV participation, and cost model. Suppress Strategy 1/2 weekly rebalance, score-exit, ATR-stop, swap, and pyramid-fraction controls for Strategy 4.
- Label results with the latest stored market session and distinguish realized P&L, open-position marked value, and hypothetical liquidation proceeds.
- **Done when:** an operator can trace any proposal back to its signal and inputs without reading JSON or confusing a simulated fill with an executed order.

### 11. Validate, replay, and roll out in stages

- Add indicator parity, engine unit, artifact/idempotency, API, ledger, and full replay tests. Include missing bars, stale universe, partial history, gap opens, fees, no cash, more than 15 candidates, and repeated first-cross. Run existing Strategy 1/2 action/backtest tests to detect regressions.
- Run historical replay and a shadow/paper cycle using current completed data. Reconcile each signal and action with the standalone script and verify no lookahead or duplicate orders. Compare daily cash and positions, not just final return.
- The current Strategy 4 event study **did not meet its Phase 1 validation gate**. Expose that status on reports and keep live execution off by default. A later decision to trade should use a separately documented evidence/acceptance review; implementation completion alone does not establish an edge.
- **Done when:** the automated gates pass, parity differences are resolved or versioned, and the paper-cycle audit is reproducible from saved artifacts.

## Suggested implementation order

`1 → 2–4 → 5 → 6 → 7–8 → 9 → 10 → 11`

Tasks 2–4 can be developed independently after Task 1. Task 6 is the common decision core; actions and backtests must both call it. The first reviewable milestone is Task 5 (daily signals and ranking), the second is Tasks 6–9 (proposal/replay parity), and the final milestone is Task 11 (shadow validation and deployment readiness).

## Pending items

- **Pyramiding research and implementation (deferred):** do not include add orders in the initial Strategy 4 integration. Preserve the prior on/off backtests as research evidence. If resumed, compare the current fresh-breakout/zero-old-risk rule with ATR-continuation triggers and a shared per-stock nominal risk budget across the same universes and time windows. Define acceptance criteria before choosing a variant. Research notes: `docs/strategy4-pyramiding-research.md`; run comparison: `backtesting_results/strategy4_totalmarket_comparison_20260928.md`.
