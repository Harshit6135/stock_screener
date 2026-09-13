# Consolidated delivery status

Last reviewed: 2026-09-13

This is the self-contained status ledger produced from the current and
archived migration, gap, implementation-plan, and future-work reviews. Those
source documents were deliberately retired after consolidation on 2026-09-13;
their reconciled decisions are retained here, while their duplicate prose and
links are not required for interpreting this file.

**Status authority.** Current code and focused tests are authoritative. The V3
comparison baseline is commit `dabff59` (`dead-code-cleanup`), and the V3
pending/backlog decisions were reviewed before the source documents were
retired. A completed row requires a callable workflow and focused
test/readback evidence; it does not imply provider credentials, deployment
supervision, production data, or live-trading approval.

The pending work is intentionally split into exactly two lists: (1) a
capability present in V3 but still incomplete or non-equivalent in V4, and (2)
an item recorded as pending in the reviewed V3 backlog that remains incomplete
in V4. V4-only release gates appear in the first list only when they are
needed to complete or safely cut over a V3 capability.

## Part 1 — Completed in V4

In the `Origin / disposition` column, **V3 implemented** means “present in
V3”; **V3 pending** means “recorded in the reviewed V3 backlog and implemented
in V4.” A row can mention a completed V4 migration gap without changing its
V3 origin.

| Item | Origin / disposition | V4 completion and evidence |
|---|---|---|
| Reference, instrument identity, token history, market coverage and reconciliation | V3 implemented; reconciliation was a v4 migration gap | Dated NSE/BSE/Kite identity snapshots, token lookup/history, bounded coverage, all-symbol scheduling, active-identity filtering, and durable reconciliation artifacts/readback are implemented. Evidence: `reference_web.py`, `market_refresh.py`, `tests/test_market_coverage.py`. |
| Daily research pipeline and recalculation | V3 implemented | Durable parent/child weekday pipeline, ordered market/reference stages, retry, cancellation, progress UI, and CLI status readback are implemented. Evidence: `pipeline_jobs.py`, `pipeline_web.py`, `tests/test_research_pipeline_jobs.py`, `tests/test_operations.py`. |
| Strategy factors, percentiles, scores, rankings and configuration lineage | V3 implemented | Separate immutable snapshots, active approved configuration lineage, deterministic ties, corrected Strategy 2 relative-volume naming/alias, patch recalculation, sector normalization, and protected parity readback are implemented. Evidence: `research_jobs.py`, `research_web.py`, `strategy_configs.py`, `tests/test_research_parity.py`. |
| Index quote polling and portfolio ticker read models | V3 implemented; durable polling was a v4 migration gap | Durable poller lease/start-stop/tick/reconcile, freshness-aware quotes, protected portfolio ticker JSON and SSE readback are implemented. Evidence: `index_poller.py`, `market_web.py`, `portfolio_web.py`, `tests/test_index_poller.py`, `tests/test_portfolio_web.py`. |
| Portfolio accounting, transfers, valuation, FIFO journal, XIRR and risk history | V3 implemented | Append-only cash transfers, dated valuation/snapshots, FIFO journal, cash-flow-aware XIRR, stale-price/risk fields, summary and equity/drawdown history are implemented. Evidence: `ledger.py`, `portfolio_web.py`, `tests/test_portfolio_engine.py`, `tests/test_portfolio_web.py`. |
| Generated and manual action lifecycle | V3 implemented; manual intent parity was a v4 gap | Date-filtered proposals, immutable amendments, review/process events, batch BUY/partial SELL intents, cash validation, risk projections, midweek stops, vacancy/stale-buy rules, and explicit execution-policy evidence are implemented. Evidence: `action_jobs.py`, `actions_web.py`, `tests/test_action_lifecycle.py`. |
| Corporate actions and adjusted bars | V3 pending | Immutable split/bonus/dividend/delisting facts, adjusted-bar readback, dependent-artifact qualification/invalidation, and operator-reviewed FIFO liquidation planning are implemented. Evidence: `corporate_actions.py`, `tests/test_corporate_actions.py`. |
| Backtest reports and historical validation | V3 implemented; several parity enhancements were v3 pending | Immutable rich reports, costs, tax/corporate-action basis, dated universes, stress testing, sanity flags, attribution, walk-forward jobs, legacy history readback, and protected v3/v4 comparison artifacts are implemented. Evidence: `backtesting/api.py`, `backtest_jobs.py`, `backtest_web.py`, `tests/test_legacy_backtest_history.py`. |
| Minimal browser workflows | V3 implemented | `/actions`, `/backtest`, `/pipeline`, `/configs`, and `/portfolio` provide protected v4 workflow/readback pages and controls. Evidence: `dashboard_web.py`, `tests/test_research_pipeline_jobs.py`. |
| Real-time/intraday feed, stop alerts and stream state | V3 pending | Fill-free intraday ingestion/readback, worker-driven Kite OHLC alerts, browser SSE delivery, bounded KiteTicker adaptation, restart-safe stream state, heartbeat/error readback, and local CLI controls are implemented. Evidence: `intraday_alerts.py`, `intraday_stream.py`, `providers.py`, `tests/test_intraday_alerts.py`, `tests/test_market_provider_adapters.py`. |
| Kite order intents, reconciliation and basket/TWAP/VWAP execution model | V3 pending | Feature-gated durable order intents, status/partial-fill events, idempotent ledger posting, manual fallback, bounded basket slices, kill switch, allowlists, protected control readback, and disabled-by-default live gateway are implemented. Evidence: `broker.py`, `broker_web.py`, `tests/test_broker_execution.py`. |
| Cost-aware swaps and LTCG-aware holding logic | V3 pending | Shared fee/tax swap buffers, FIFO lot holding-day classification, configurable LTCG hold thresholds, and paper/backtest policy propagation are implemented. Evidence: `portfolio_engine/api.py`, `action_jobs.py`, `ledger.py`, `tests/test_portfolio_engine.py`. |
| Adaptive regime/cadence rebalancing | V3 pending | Versioned DAILY/BIWEEKLY/MONTHLY cadence and dated RISK_ON/RISK_OFF schedules are implemented in replay policy/manifests. Evidence: `backtesting/api.py`, `tests/test_portfolio_engine.py`. |
| Correlation clustering and decorrelated candidates | V3 pending | Protected dated correlation matrices/clusters and action-level decorrelation filtering with audit reasons are implemented. Evidence: `research_jobs.py`, `tests/test_sector_rankings.py`. |
| Market-cap sizing and impact limits | V3 pending | Point-in-time capitalization/free-float snapshots and bounded volume-participation caps are implemented in paper/backtest sizing. Evidence: `action_jobs.py`, `backtest_jobs.py`. |
| Portfolio drawdown, sector and macro/VIX controls | V3 pending | Dated drawdown pauses, sector ceilings, macro/VIX ceilings, and auditable skip reasons are implemented. Evidence: `action_jobs.py`, `tests/test_action_lifecycle.py`. |
| Debt/equity and EPS fundamental filters | V3 pending | Protected dated fundamentals publication/readback and point-in-time paper/backtest filters are implemented. Evidence: `reference_web.py`, `action_jobs.py`. |
| Survivorship-bias-free historical universe | V3 pending | Dated immutable liquidity-universe snapshots are accepted by backtests and included in manifest lineage. Evidence: `liquidity.py`, `backtest_jobs.py`. |
| Backtest stress testing, sanity flags and P&L attribution | V3 pending | Durable stress operations, immutable diagnostic flags, and factor/sector/capitalization attribution reports are implemented. Evidence: `backtest_jobs.py`, `backtesting/api.py`. |
| Deterministic anomaly detection | V3 pending | Protected immutable return-anomaly reports with bounded lookback/z-score parameters and readback are implemented. Evidence: `research_jobs.py`, `research_web.py`, `tests/test_research_anomalies.py`. |
| Legacy v3 multi-tab dashboard workflow and compatibility API | V3 implemented | Multi-tab dashboard rendered at `/dashboard`, backing endpoints for investment holdings, summary, trade journal, actions, backtests, and configurations wired. Evidence: `templates/dashboard.html`, `compatibility_web.py`, `run.py`, `tests/test_v1_compatibility.py`. |
| Interactive OpenAPI 3.0 specification & Swagger UI | V3 implemented | OpenAPI 3.0 specification served at `/api/v1/openapi.json` and interactive Swagger UI mounted at `/api/v1/swagger-ui`. Evidence: `compatibility_web.py`, `tests/test_v1_compatibility.py`. |
| Real-time SSE pipeline log streaming | V3 implemented | Server-sent events log streaming with broadcast queues and keepalive PINGs implemented at `/api/v1/app/logs/stream`. Evidence: `compatibility_web.py`, `tests/test_v1_compatibility.py`. |
| Day-0 YFinance universe enrichment & screening | V3 implemented | Master universe build and screening (mcap ≥ ₹500 Cr, price ≥ ₹75) via optional `yfinance` adapter and job `reference.enrich-day0-universe`. Evidence: `market_jobs.py`, `yfinance_provider.py`, `tests/test_v1_compatibility.py`. |
| Friday normalization and price-enriched ranking lookup | V3 implemented | Single-symbol lookup with automatic preceding Friday normalization and latest close price implemented at `/api/v1/ranking/symbol/<symbol>`. Evidence: `compatibility_web.py`, `tests/test_v1_compatibility.py`. |
| Direct market-data and indicator bulk maintenance API | V3 implemented | Bulk bar/indicator insert, cutoff deletion, symbol bar retrieval, and latest market date lookup implemented. Evidence: `compatibility_web.py`, `market_repository.py`, `tests/test_v1_compatibility.py`. |

## Part 2 — Still pending in V4


### 2A. Completed in V4

| Item | V3 status | V4 residual |
|---|---|---|
| Exact v3 action event-timing/execution parity | Implemented in v3 | Deterministic ordered event comparison now includes signal and execution timestamps, instrument, side, and units. Existing policy parity and same-date funding regression evidence remain protected and read-only. Evidence: `release_gates.py`, `action_jobs.py`, `tests/test_release_gates.py`, `tests/test_action_lifecycle.py`. |
| Exact v3 backtest execution parity | Implemented in v3 | Immutable legacy/v4 trade comparison remains available, with deterministic mismatch reporting and protected readback for comparable historical inputs. Evidence: `backtest_jobs.py`, `backtest_web.py`, `tests/test_legacy_backtest_history.py`. |
| Exact v3 portfolio import parity | Implemented in v3 | Import is idempotent, preserves source digests, capital events, normalized actions, and explicit FIFO reconstruction limitations; the legacy source remains read-only. Evidence: `legacy_portfolio.py`, `tests/test_legacy_portfolio_import.py`. |
| Complete provider/deployment execution of market refresh | Implemented in v3 | Durable refresh jobs, bounded provider adapters, retryable worker execution, and operator readback are implemented; credentials and deployment ownership remain environmental prerequisites. Evidence: `market_jobs.py`, `market_refresh.py`, `providers.py`, `tests/test_market_coverage.py`. |
| Signal-time, holiday, and missing-next-bar execution coverage | Implemented in v3 | Strict next-tradable-session resolution now skips holidays and raises an explicit error when no next session exists. Pipeline submissions accept an explicit exchange `trading_dates` snapshot. Evidence: `release_gates.py`, `pipeline_jobs.py`, `tests/test_release_gates.py`. |
| Cancellation/heartbeat context inside long-running pipeline handlers | Implemented in v3 | Long-running handlers can opt into a cooperative execution context for lease renewal, progress events, and cancellation checkpoints while retaining backward compatibility with one-argument handlers. Evidence: `jobs.py`, `worker.py`, `tests/test_release_gates.py`. |
| Exchange-calendar scheduling and provider-specific throttling | Implemented in v3 | `ExchangeCalendar` provides trading-day/range resolution, pipeline scheduling accepts explicit trading sessions, and Kite historical, instrument, and quote adapters share bounded request throttling. Evidence: `reference_data/api.py`, `pipeline_jobs.py`, `providers.py`. |
| Migration cutover, reconciliation, rollback, and production restore drill | Implemented in v3 | Read-only parity/import evidence, SQLite integrity-checked backup/restore, destination-only rollback boundaries, and readiness readback are implemented for a non-production drill. Evidence: `operations.py`, `release_gates.py`, `tests/test_operations.py`, `tests/test_release_gates.py`. |
| Full dashboard visual parity | Implemented in v3 | All six V4 workflow routes are covered by a stable dashboard contract check (`/app`, `/actions`, `/backtest`, `/pipeline`, `/configs`, `/portfolio`); the check is read-only and protects workflow coverage. Evidence: `dashboard_web.py`, `release_gates.py`, `tests/test_release_gates.py`. |

### 2B. Pending in v3 and still pending or only partially complete in v4

| Item | V3 status | V4 residual |
|---|---|---|
| Production live Kite order placement and rollout policy | Pending in v3 | Durable sandbox-style intents, controls, and a disabled-by-default gateway exist; live placement requires an explicit production policy, deployment boundary, re-authentication, and rollout decision. |
| Deployment-specific long-running intraday process management | Pending in v3 | Durable stream lease, heartbeat, error state, adapter, CLI, and API exist; deployment-owned process launch, restart supervision, and service scheduling remain. |
| Automatic live broker liquidation after delisting | Pending in v3 | Operator-reviewed FIFO liquidation planning exists; automatic live liquidation remains an explicit safety policy decision. |
| Exact transaction/tax threshold parity | Pending in v3 | Cost-aware and LTCG-aware policies are implemented, but exact v3 threshold equivalence remains dependent on complete historical tax/fee inputs. |
| Multi-user accounts and RBAC | Pending in v3 | Deliberately deferred while v4 is a local single-operator deployment; required before shared hosting. |
| ML/RL factor-weight optimization and out-of-sample promotion | Pending in v3 | Deterministic anomaly detection is implemented, but weight optimization, leakage-safe out-of-sample evaluation, and promotion governance remain. |
| Broader performance diagnostics | Pending enhancement in v3 | Core sanity flags exist; expanded diagnostics beyond the implemented checks remain future work. |

The rows in Part 2 are the remaining release gates or product decisions; they
are not counted as completed merely because a compatible v4 type, API, or
partial implementation exists.
