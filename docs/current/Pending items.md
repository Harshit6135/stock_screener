# Pending items

Comparison baseline: the clean v3 `dead-code-cleanup` worktree at `dabff59`
versus the current v4 working tree on 12 September 2026. The
[code audit](V3%20code%20audit%20and%20V4%20comparison.md) inventories the v3
routes and dashboard; the [migration ledger](V3%20to%20V4%20feature%20migration%20ledger.md)
records implemented slices. This page tracks what remains. An API name or a
domain class alone does not close a row: the v4 workflow must be callable and
its result queryable end to end.

## V4 delivery priority

`P0` closes data and research dependencies first; `P1` restores portfolio
and decision correctness; `P2` completes historical validation and operator
workflows; `P3` adds the optional research/risk enhancements; `P4` requires
an explicit live-service or multi-user rollout; `P5` is exploratory research.
Within each tier, implement upstream data and policy before consumers. The
archived v3 priority labels below are retained for provenance, not used as the
v4 execution order. The completed P0 slices are market coverage/latest-date
readback and dated token lookup/change history. Daily reconciliation and
all-symbol scheduling are next.

## Open v3-to-v4 migration

| V4 priority | Area | Still pending | Detailed design |
|---|---|---|---|
| P0 | Reference and market data | Daily source reconciliation and all-symbol refresh remain. Bounded coverage/latest-date readback and dated token assignment/change-history APIs are implemented. | [§8](Pending%20migration%20implementation%20design.md#8-reference-and-market-data-reconciliation), [§9](Pending%20migration%20implementation%20design.md#9-read-models-and-minimal-replacement-pages) |
| P0 | Daily pipeline | Reference/market stages, trading-calendar date ranges, failed-stage retry, cancellation propagation and browser progress | [§1](Pending%20migration%20implementation%20design.md#1-daily-pipeline-and-recalculation) |
| P0 | Research and ranking | Symbol/date/latest feature, percentile, score and ranking reads; ranking close/history; controlled patch and non-destructive range recalculation; formula/candidate/tie parity and approved research-config selection | [§1](Pending%20migration%20implementation%20design.md#1-daily-pipeline-and-recalculation), [§4](Pending%20migration%20implementation%20design.md#4-strategy-parity-and-approved-configuration-use), [§9](Pending%20migration%20implementation%20design.md#9-read-models-and-minimal-replacement-pages) |
| P0 | Strategy configuration | Import/alias v3 named configs, use an approved revision in research jobs, validate Strategy 2 semantics | [§4](Pending%20migration%20implementation%20design.md#4-strategy-parity-and-approved-configuration-use) |
| P1 | Corporate actions | Adjusted-bar revisions and dependent-artifact invalidation | [§3](Pending%20migration%20implementation%20design.md#3-corporate-actions-and-adjusted-bars) |
| P1 | Index and portfolio prices | Durable quote polling lifecycle, portfolio ticker/read model, dated valuation and freshness | [§2](Pending%20migration%20implementation%20design.md#2-continuous-index-quotes), [§6](Pending%20migration%20implementation%20design.md#6-portfolio-valuation-and-journal) |
| P1 | Portfolio | Cash infusions/withdrawals, dated holdings and equity history, FIFO trade journal, XIRR, unrealised gain and stop-based risk metrics | [§6](Pending%20migration%20implementation%20design.md#6-portfolio-valuation-and-journal), [§10](Pending%20migration%20implementation%20design.md#10-amendments-cash-transfers-and-valuation) |
| P1 | Generated actions | Date/calendar read model, individual amendments and bulk review, midweek stop/vacancy and stale-buy rules, approval cash re-sizing, optional pyramid adds, trailing-stop state | [§5](Pending%20migration%20implementation%20design.md#5-action-lifecycle-parity), [§9](Pending%20migration%20implementation%20design.md#9-read-models-and-minimal-replacement-pages) |
| P1 | Manual actions | Reviewable operator-created BUY/SELL intents, including batch BUY, partial SELL and reason/validation; direct paper fills alone do not provide this flow | [§10](Pending%20migration%20implementation%20design.md#10-amendments-cash-transfers-and-valuation) |
| P2 | Backtest | Long periods, daily-stop/midweek/pyramid modes, corporate-action and cost basis, full v3 metrics/annual returns/trade log/open-position treatment, report UI, historical trade parity and read-only access to saved v3 run history | [§7](Pending%20migration%20implementation%20design.md#7-backtest-parity) |
| P2 | Browser workflows | `/actions` and `/backtest` pages, pipeline/config/portfolio/manual-trade controls, valuation/journal and report readback | [§9](Pending%20migration%20implementation%20design.md#9-read-models-and-minimal-replacement-pages) |
| P4 | Broker execution | Feature-gated Kite order intents, status/partial-fill reconciliation, idempotent ledger posting and conflict-safe manual fallback | [§11](Pending%20migration%20implementation%20design.md#11-gated-kite-execution-and-broker-reconciliation) |

V3's in-place bulk deletes, global web-process polling threads and destructive
backtest deletion are intentionally replaced by durable jobs and immutable
artifacts. The broken v3 `/actions` template route is not a visual-parity
target; the action workflow still needs a working v4 page.

## Carried-forward v3 future backlog

The [archived v3 pending list](../archive/v3/Pending%20items.md) labelled
these as future work when it was written in February 2026. The later v3
worktree did add a portfolio WebSocket ticker and dashboard live-P&L view;
their v4 parity is tracked in the migration table above. The broader items
below remain product enhancements. None should be treated as completed merely
because a v4 type or design mentions it.

| V4 priority | Priority in v3 | Item | V4 disposition |
|---|---|---|---|
| P3 | High | Real-time/intraday Kite feed and streaming stop alerts | V3's portfolio ticker/dashboard view needs v4 parity above; broader intraday research feed and alerts remain pending. |
| P4 | High | Kite order placement and basket/TWAP/VWAP execution | Pending; [gated execution design](Pending%20migration%20implementation%20design.md#11-gated-kite-execution-and-broker-reconciliation) covers basic orders, while basket and execution algorithms need a later policy. |
| P3 | High | Sector-normalized factor ranking | Pending; requires dated sector classification and a versioned ranking policy. |
| P3 | Medium | Transaction- and tax-cost-aware swap buffer | Pending; use explicit cost/tax assumptions in the policy and parity tests. |
| P3 | Medium | LTCG-aware hold recommendation in swap logic | Pending; preserve acquisition lots and tax-policy dates. |
| P3 | Medium | Regime-based bi-weekly/monthly rebalancing | Pending; add a versioned calendar/regime policy and replay comparison. |
| P3 | Medium | Correlation clustering/heatmap and decorrelated candidates | Pending; requires a point-in-time return window and portfolio UI. |
| P3 | Medium | Market-cap-scaled position sizing | Pending; requires a dated, verified capitalization source. |
| P3 | Medium | Drawdown pause, sector concentration and macro/VIX portfolio controls | Pending; stop/risk projections alone do not implement these portfolio gates. |
| P3 | Medium | Debt/equity and EPS fundamental filters | Pending; requires dated fundamentals with missing-data policy. |
| P2 | Low | Historical constituents for survivorship-bias-free backtests | Pending; use dated universe snapshots rather than today's members. |
| P3 | Low | Walk-forward backtesting | Pending; compare multiple rolling train/test windows. |
| P1 | Low | Split/bonus/dividend and delisting handling | Partly designed in [§3](Pending%20migration%20implementation%20design.md#3-corporate-actions-and-adjusted-bars); delisting/removed-listing liquidation policy remains pending. |
| P3 | Low | Market-impact limit in position sizing | Pending; use a volume/liquidity-aware fill and sizing policy. |
| P3 | Low | Backtest stress testing | Pending; vary costs, universe and portfolio scaling across scenarios. |
| P2 | Low | Unrealistic-performance sanity flags | Pending; flag outlier Sharpe, concentration and other implausible results. |
| P3 | Low | P&L attribution by factor, sector and market cap | Pending; retain the necessary dated factor/classification lineage. |
| P4 | Low | Multi-user accounts and RBAC | Deferred while v4 is local single-operator; required before shared hosting. |
| P5 | Low | AI/ML weight optimization and anomaly detection | Pending research, subject to out-of-sample validation. |
