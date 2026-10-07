# Stock Screener & Portfolio Management (v2) - Comprehensive Codebase Audit

**Date:** October 5, 2026  
**Audited Target:** `stocks_screener_v2` (Local Modular Monolith Web App)  
**Scope:** Complete file-by-file audit of architecture, domain modules, application gates, workflows, HTTP endpoints, static assets, templates, configurations, data storage, and operational scripts (excluding `tests/`).

---

## 1. Executive Summary & Architectural Overview

The application is structured as a **local-first modular monolith** written in Python 3.13, using Flask 3.1 as the HTTP adapter, Waitress 3.0 as the WSGI server, SQLite with WAL mode as the single persistent storage engine, and Vanilla JS / CSS on the browser front end. It is designed to run locally on `127.0.0.1:5000` with direct access to Zerodha Kite Connect for historical and live market data.

### Architectural Tiers:
```
[ Browser UI / Vanilla JS ]
          │
          ▼ HTTP / SSE
[ Application Gates (src/gates/http) ]
          │
          ▼ Orchestration
[ Application Workflows (src/gates/workflows) ]
          │
          ▼ Business Rules & Aggregates
[ Domain Owners (src/domains/*) ]
          │
          ▼ Shared Primitives & Infrastructure
[ Platform Kernel (src/platform_kernel/*) + SQLite Stores ]
```

### Key Strengths:
1. **Strict Dependency Inversion & Auditability:** research rankings, signal evaluations, and backtest results are modeled as immutable, content-addressed JSON artifacts recorded with SHA-256 digests and upstream lineage.
2. **Double-Entry Style Portfolio Ledger:** Portfolio accounting uses an event-sourced ledger (`ledger_accounts`, `ledger_events`, `ledger_commands`) with optimistic concurrency checks (`expected_version`) and idempotency keys to prevent double-fills or duplicate cash transfers.
3. **Robust Risk Management:** A central `ManagedRiskGuard` validates portfolio allocations, ADV participation limits, sector concentration, and order sizes prior to creating broker intents.

---

## 2. File-by-File Detailed Audit

---

### A. Platform Kernel (`src/platform_kernel/`)

The platform kernel provides framework-agnostic types, validation errors, SQLite connection managers, and security redactions.

#### 1. [`src/platform_kernel/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/platform_kernel/__init__.py)
* **Functionality:** Re-exports contracts, artifact storage classes, error types, and dependency inversion ports.
* **Complexity & Improvements:** Clean and standard.
* **Dead Code / Removable:** Re-exports `VersionedReference`, `CommandMetadata`, `LiveQuoteProvider`, `InstrumentProvider`, and `Broker` which are largely unused across the codebase.
* **Bugs / Missing Features:** None.

#### 2. [`src/platform_kernel/api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/platform_kernel/api.py)
* **Functionality:** Second re-export module mirroring `__init__.py`.
* **Complexity & Improvements:** Redundant with `__init__.py`. Having two identical facade files in the same directory (`__init__.py` and `api.py`) creates import ambiguity.
* **Dead Code / Removable:** Consolidate into `__init__.py` or keep one canonical export location.
* **Bugs / Missing Features:** None.

#### 3. [`src/platform_kernel/artifacts.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/platform_kernel/artifacts.py)
* **Functionality:** Implements crash-safe, immutable JSON artifact storage (`ArtifactStore` protocol and `SqliteArtifactStore`). Writes payloads and metadata manifests atomically, validates SHA-256 checksums, and manages staging and quarantine states.
* **Complexity & Improvements:** Extremely solid. Well-isolated transaction boundaries and quarantine handling for corrupted files.
* **Dead Code / Removable:** `has_payloads()` in `SqliteArtifactStore` is only called in diagnostic scenarios.
* **Bugs / Missing Features:** Lacks automated payload compression (zstandard or gzip). Because large feature matrices and backtests are stored as uncompressed JSON in SQLite or filesystem blobs, disk usage balloons quickly over time.

#### 4. [`src/platform_kernel/contracts.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/platform_kernel/contracts.py)
* **Functionality:** Defines core value objects: `FrozenDict`, `freeze_value`, `Money`, `Quantity`, `VersionedReference`, and `CommandMetadata`.
* **Complexity & Improvements:** `Money` and `Quantity` provide strict decimal validation and positive-integer guarantees.
* **Dead Code / Removable:** `VersionedReference` and `CommandMetadata` are defined here but never instantiated or referenced anywhere in domain models or gates.
* **Bugs / Missing Features:** `Money` only supports a single hardcoded currency default (`INR`). Multi-currency support is unnecessary, but currency conversion arithmetic is absent.

#### 5. [`src/platform_kernel/errors.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/platform_kernel/errors.py)
* **Functionality:** Defines `DomainValidationError(ValueError)`, the primary exception for invariant failures.
* **Complexity & Improvements:** Clean, lightweight.
* **Dead Code / Removable:** None.
* **Bugs / Missing Features:** Could benefit from error sub-types (e.g. `NotFoundError`, `ConflictError`, `ConcurrencyError`) to avoid fragile string matching (`"not found"` or `"stale"` checks) in HTTP blueprint handlers.

#### 6. [`src/platform_kernel/ports.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/platform_kernel/ports.py)
* **Functionality:** Defines Python protocols: `HistoricalBarsProvider`, `InstrumentProvider`, `LiveQuoteProvider`, and `Broker`.
* **Complexity & Improvements:** Clean interfaces.
* **Dead Code / Removable:** `LiveQuoteProvider` and `Broker` are never used as formal type annotations in workflow constructors (most components use duck typing or concrete adapters).
* **Bugs / Missing Features:** Methods in `HistoricalBarsProvider` return `Sequence[object]`, which forfeits static type verification for bar properties (`open`, `high`, `low`, `close`, `volume`).

#### 7. [`src/platform_kernel/security.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/platform_kernel/security.py)
* **Functionality:** Redacts API keys, secrets, tokens, passwords, cookies, and bearer credentials from dictionaries, strings, exception messages, and log records.
* **Complexity & Improvements:** Excellent security hygiene; prevents accidental leakage of Kite API credentials into logs, SQLite jobs, or UI error payloads.
* **Dead Code / Removable:** None.
* **Bugs / Missing Features:** None.

#### 8. [`src/platform_kernel/sqlite.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/platform_kernel/sqlite.py)
* **Functionality:** Centralized SQLite connection context manager (`sqlite_connection`) and namespaced migration executor (`migrate_sqlite`). Enforces `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`, and `PRAGMA journal_mode=WAL`.
* **Complexity & Improvements:** High quality. Provides reliable atomic schema migrations without requiring heavy external dependencies like Alembic.
* **Dead Code / Removable:** None.
* **Bugs / Missing Features:** SQLite connection has a fixed 5,000ms busy timeout. Under heavy multi-step research pipeline jobs or backtest walk-forward writes, concurrent connections occasionally encounter `sqlite3.OperationalError: database is locked`. Increasing `busy_timeout` to 30,000ms or serializing write transactions via a connection pool is recommended.

---

### B. Domain Modules (`src/domains/`)

---

#### Module: `artifacts`
* **[`src/domains/artifacts/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/artifacts/__init__.py):** Re-exports `ArtifactCatalog` and `ArtifactPublisher`.
* **[`src/domains/artifacts/catalog.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/artifacts/catalog.py):**
  * *Functionality:* SQLite catalog (`artifact_catalog`, `artifact_supersessions`, `artifact_invalidations`) maintaining lineage and active state of published research and backtest artifacts.
  * *Complexity & Better Approaches:* Contains complex supersession graph traversal. Uses iterative SQL queries for invalidation trees. A recursive CTE query would be faster and cleaner.
  * *Dead Code:* `set_status()` has zero external callers outside legacy tests.
  * *Bugs/Missing Features:* Lacks index on `(category, created_at)` which causes sequential table scans when querying large historical runs.
* **[`src/domains/artifacts/publication.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/artifacts/publication.py):**
  * *Functionality:* Coordinates publishing JSON content to `ArtifactStore` and cataloging it atomically.
  * *Complexity & Improvements:* Clean 2-phase publish: stage -> store -> register in catalog.

---

#### Module: `market_data`
* **[`src/domains/market_data/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/market_data/__init__.py):** Public package exports.
* **[`src/domains/market_data/api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/market_data/api.py):** Defines `NormalizedBar` and `MarketDataSnapshot` dataclasses.
* **[`src/domains/market_data/schema.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/market_data/schema.py):** Creates tables for `market_bars`, `market_fetch_coverage`, `market_history_revisions`, `market_indicators`, `data_quality_events`.
* **[`src/domains/market_data/history_repository.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/market_data/history_repository.py) (648 lines):**
  * *Functionality:* Core persistence for bars, indicator caches, fetch coverage windows, quality anomaly checks (price gaps > 15%, 6+ zero-volume streaks), and history revisions.
  * *Complexity & Improvements:* In `upsert_bars`, checking if existing bars changed uses an expensive O(N) Python loop comparing decimals as strings (`Decimal(str(row["open"])) != Decimal(str(incoming[...]))`). This can be done directly in SQL or batched vectorized comparison.
  * *Dead Code:* `apply_price_factor` is a redundant predecessor to `CorporateActions.adjust_corporate_event`. `delete_bars_after()` has no callers in production.
  * *Bugs / Issues:* `bars()` default date range is `2000-01-01` to `2099-12-31`. Query returns bars ordered descending then re-sorted ascending in memory; for large histories, lack of `limit` indexing causes full index scans.
* **[`src/domains/market_data/index_quotes.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/market_data/index_quotes.py):** Persists benchmark index quotes (NIFTY 50, NIFTY 500, INDIA VIX) into `market_index_quotes`. Clean and simple.
* **[`src/domains/market_data/live_quotes.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/market_data/live_quotes.py):** Maintains `live_quotes` table with TTL-based freshness validation for intraday execution pricing.
* **[`src/domains/market_data/providers.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/market_data/providers.py) (352 lines):**
  * *Functionality:* Rate-limited API client adapters: `KiteHistoricalBarsProvider`, `KiteInstrumentProvider`, `KiteQuoteProvider`, and `NseHistoricalBhavcopyProvider`.
  * *Complexity & Improvements:* `_ProviderThrottle` implements token-bucket delays using `time.sleep()`. In `KiteHistoricalBarsProvider.get_bars_with_quality`, pagination and split recovery logic is overly convoluted.
  * *Bugs / Edge Cases:* `NseHistoricalBhavcopyProvider` uses hardcoded NSE headers and cookies that frequently get blocked by NSE's anti-scraping Akamai CDN without rotating user-agents or session refreshes.
* **[`src/domains/market_data/repository.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/market_data/repository.py):** Empty subclass `class MarketRepository(MarketHistoryRepositoryMixin, IndexQuoteRepositoryMixin): pass`. This is an unnecessary stub because `src/gates/repositories.py` defines the actual composite `MarketRepository`.

---

#### Module: `reference_data`
* **[`src/domains/reference_data/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/reference_data/__init__.py):** Re-exports models and repository.
* **[`src/domains/reference_data/api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/reference_data/api.py) (492 lines):**
  * *Functionality:* Defines models for `Instrument`, `InstrumentAlias`, `UniverseSnapshot`, `LiquidityUniverseSnapshot`, `ExchangeCalendar`.
  * *CRITICAL BUG:* **Class name collision!** Line 339 defines `@dataclass(frozen=True) class CorporateAction:`, and line 472 defines `class CorporateAction(NamedTuple):`. The second declaration completely shadows and overwrites the first in the same module namespace!
  * *Complexity & Improvements:* `build_liquidity_universe()` computes rolling 30-day median turnover across all candidates in pure Python loops.
* **[`src/domains/reference_data/nse_provider.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/reference_data/nse_provider.py):** Downloads Nifty 500 constituents CSV from `archives.nseindia.com` and corporate actions announcements from NSE API.
* **[`src/domains/reference_data/repository.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/reference_data/repository.py) (659 lines):**
  * *Functionality:* Stores `reference_instruments`, `reference_instrument_tokens`, `universe_snapshots`, `universe_snapshot_members`, `corporate_action_events`, and exit eligibility queues.
  * *Complexity & Improvements:* `universe_snapshot_diff()` compares sets of members between two snapshots. Clean.
  * *Dead Code:* `exit_eligible_instruments()` contains redundant queries.
* **[`src/domains/reference_data/schema.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/reference_data/schema.py):** Namespaced migration for reference tables.

---

#### Module: `indicators`
* **[`src/domains/indicators/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/indicators/__init__.py):** Exports DAG models, Pandas TA adapter, and node caching.
* **[`src/domains/indicators/api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/indicators/api.py):** Indicator revision definitions.
* **[`src/domains/indicators/dag.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/indicators/dag.py) (652 lines):**
  * *Functionality:* Declarative execution graph for indicators. Validates node dependencies, detects circular references, computes execution order via topological sort, and evaluates series with Pandas TA or numpy vectorization.
  * *Complexity & Improvements:* Highly complex custom DAG runner. Contains custom piecewise interpolation and mathematical operations (`_execute_operation`, `_interpolate_piecewise`). While flexible, debugging failed nodes inside large YAML pipelines is difficult due to generic error wraps.
* **[`src/domains/indicators/momentum_quality.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/indicators/momentum_quality.py):** Calculates 6-month and 12-month returns, 14-day RSI, Bollinger Bands %B, and 14-day ATR.
* **[`src/domains/indicators/node_cache.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/indicators/node_cache.py) (337 lines):**
  * *Functionality:* SQLite content-addressed cache (`indicator_node_cache`) keyed by SHA-256 node hash, instrument ID, and date.
  * *Note on Usage:* Currently has 0 rows in active runtime because strategies utilize bulk recalculation or `market_indicators` tables. Cache layer adds overhead if not utilized.
* **[`src/domains/indicators/registry.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/indicators/registry.py):** Whitelist registry of approved `pandas-ta` functions (`sma`, `ema`, `rsi`, `bbands`, `atr`, `supertrend`, etc.) with strict parameter specs. Excellent security sandboxing against arbitrary code execution.
* **[`src/domains/indicators/relative_strength.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/indicators/relative_strength.py):** Benchmark-relative return ratio, rolling percentiles, and cross-sectional factor ranking.

---

#### Module: `strategies`
* **[`src/domains/strategies/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/strategies/__init__.py):** Package entry point.
* **[`src/domains/strategies/api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/strategies/api.py) (386 lines):** Strategy revision contracts, percentile calculation helpers (`rank_feature_values`), and snapshot builders.
* **[`src/domains/strategies/definitions.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/strategies/definitions.py) (434 lines):** Parses and validates declarative YAML strategy definitions against indicator registry rules.
* **[`src/domains/strategies/momentum_quality.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/strategies/momentum_quality.py):** Composite scoring function implementing Goldilocks RSI bands (50 <= RSI <= 70) and positive %B ranking.
* **[`src/domains/strategies/positional_trend.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/strategies/positional_trend.py):** Point-in-time signal generator for Positional Trend strategy: Donchian 20/55 breakouts, Supertrend (10, 3) stops, ADX > 20 filters, and 30-day ADTV liquidity checks.
* **[`src/domains/strategies/positional_trend_backtest.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/strategies/positional_trend_backtest.py) (374 lines):** Fast deterministic next-open replay simulator for positional trend following.
* **[`src/domains/strategies/positional_trend_comparison.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/strategies/positional_trend_comparison.py) (77 lines):**
  * *Dead Code:* Contains `pandas_ta_features` function which is never called anywhere in the active app. Removable.
* **[`src/domains/strategies/ranking_patterns.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/strategies/ranking_patterns.py) (190 lines):**
  * *Complexity & Dead Code:* Implements `RankingPattern`, `FactorPercentileRanking`, and `DirectSignalRanking`. Intended as a strategy pattern dispatch, but `ResearchJobs` bypasses this and executes factor/signal logic directly.

---

#### Module: `research`
* **[`src/domains/research/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/research/__init__.py) & [`api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/research/api.py):** Public interfaces for research persistence.
* **[`src/domains/research/calculations.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/research/calculations.py):** Pure statistical calculation routines: sector factor ranking, correlation clustering, and return anomaly detection.
* **[`src/domains/research/pipeline_repository.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/research/pipeline_repository.py):** Schema and queries for multi-stage pipeline runs (`research_pipelines`, `research_pipeline_stages`).
* **[`src/domains/research/repository.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/research/repository.py) (332 lines):** Stores `research_percentiles`, `research_daily_scores`, and `research_rankings`. Note: `research_percentiles` is over 850 MB in the active DB; see Storage section.

---

#### Module: `operations`
* **[`src/domains/operations/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/operations/__init__.py):** Exports `Job`, `JobStore`, `JobWorker`, `BackgroundWorker`.
* **[`src/domains/operations/jobs.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/operations/jobs.py) (705 lines):**
  * *Functionality:* Durable SQLite job queue (`ops_jobs`, `ops_job_events`) with leasing, heartbeats, exponential backoff retries, cooperative cancellation, and event cursors.
  * *Complexity & Improvements:* Well-designed leasing mechanism.
  * *Dead Code:* `cancel_kinds()` and `requeue_expired_running()` are utility methods with no production callers.
* **[`src/domains/operations/worker.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/operations/worker.py):**
  * *Functionality:* Single-writer background polling worker thread (`BackgroundWorker`).
  * *Complexity & Improvements:* `LEASE_SECONDS` is set to 3,600s (1 hour) to avoid duplicate job claims during massive bulk recalculations.
  * *Potential Bug:* If a worker process abruptly dies (SIGKILL / power loss), a claimed job remains marked `RUNNING` for an entire hour before another worker can claim it.

---

#### Module: `portfolio_accounting`
* **[`src/domains/portfolio_accounting/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_accounting/__init__.py):** Exports accounting models and `Ledger`.
* **[`src/domains/portfolio_accounting/api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_accounting/api.py):** Pure FIFO matching engine (`project()`). Computes remaining units, cash balance, and realized P&L from sequence of fills. Clean functional logic.
* **[`src/domains/portfolio_accounting/intraday_alerts.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_accounting/intraday_alerts.py):** Ingests live tick breaches against ATR / Supertrend trailing stop anchors without creating unapproved fills.
* **[`src/domains/portfolio_accounting/ledger.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_accounting/ledger.py) (563 lines):**
  * *Functionality:* Durable event-sourced portfolio ledger (`ledger_accounts`, `ledger_events`, `ledger_commands`, `ledger_valuations`). Provides FIFO journal with tax holding period classification (`LONG_TERM` vs `SHORT_TERM`).
  * *Complexity & Improvements:* Clean optimistic concurrency via `expected_version`. Valuation snapshotting includes SHA-256 payload checksums.
* **[`src/domains/portfolio_accounting/portfolio_performance.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_accounting/portfolio_performance.py):** Calculates XIRR using cash inflows, withdrawals, and current portfolio equity. Implements Newton-Raphson approximation.

---

#### Module: `portfolio_engine`
* **[`src/domains/portfolio_engine/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_engine/__init__.py):** Exports decision types and `PortfolioPolicy`.
* **[`src/domains/portfolio_engine/api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_engine/api.py) (617 lines):**
  * *Functionality:* Pure portfolio decision rules (`evaluate()`). Determines BUY, SELL, HOLD, or PYRAMID_ADD decisions based on top rankings, stop losses, max positions, and cash availability.
  * *Complexity & Improvements:* `evaluate()` is 311 lines long and handles volume caps, slippage, round-trip costs, turnover limits, and cash replenishment. Splitting into dedicated sizing and rebalancing sub-routines would significantly improve maintainability.
* **[`src/domains/portfolio_engine/proposal_store.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_engine/proposal_store.py):** Stores reviewable action proposals (`portfolio_proposals`, `portfolio_proposal_events`).
* **[`src/domains/portfolio_engine/risk_config.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_engine/risk_config.py):** Stores versioned global risk limits (`portfolio_risk_config` table): max order value, single stock allocation, ADV participation cap.
* **[`src/domains/portfolio_engine/risk_reservations.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/portfolio_engine/risk_reservations.py):** Tracks capital reservations for pending proposals and unsubmitted orders to prevent over-allocation.

---

#### Module: `execution`
* **[`src/domains/execution/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/execution/__init__.py):** Exports accounts and gateway.
* **[`src/domains/execution/accounts.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/execution/accounts.py) (199 lines):** Manages multi-account Kite Connect credentials, session tokens, and strategy-to-ledger account links (`kite_accounts`, `strategy_portfolios`).
* **[`src/domains/execution/api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/execution/api.py):** Minimal file with only docstrings. Redundant.
* **[`src/domains/execution/broker_adapter.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/execution/broker_adapter.py):** `KiteExecutionGateway` interfacing directly with `kiteconnect.KiteConnect` to place regular/AMO equity orders. Supports arming/disarming kill-switch.
* **[`src/domains/execution/kite_auth.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/execution/kite_auth.py):** Manages OAuth login flow and saves access token atomically to disk (`access_token.txt`).
* **[`src/domains/execution/order_repository.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/execution/order_repository.py) (311 lines):** Stores order intents, basket orders, slices, and broker trade fill logs in `broker_orders`, `broker_baskets`, `broker_order_events`.
* **[`src/domains/execution/streaming_provider.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/execution/streaming_provider.py):** Adapter around KiteTicker WebSocket stream for real-time tick streaming.

---

#### Module: `backtesting`
* **[`src/domains/backtesting/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/backtesting/__init__.py) & [`api.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/backtesting/api.py):** Exports.
* **[`src/domains/backtesting/event_study.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/backtesting/event_study.py) (219 lines):**
  * *Functionality:* Stationary intervals and post-signal return distributions for event studies.
  * *Dead Code:* Completely unreferenced in any HTTP blueprint, CLI command, or UI page! Removable or needs to be wired into a future feature.
* **[`src/domains/backtesting/repository.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/backtesting/repository.py):** Stores backtest summary records in `backtest_runs`.
* **[`src/domains/backtesting/simulation.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/domains/backtesting/simulation.py) (638 lines):** Replay simulator computing CAGR, Sharpe ratio, Max Drawdown, Calmar ratio, win rates, and attribution metrics without writing to the portfolio ledger.

---

### C. Application Gates (`src/gates/`)

---

#### Root Gate Files
* **[`src/gates/__init__.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/__init__.py):** Empty docstring.
* **[`src/gates/app.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/app.py) (220 lines):**
  * *Functionality:* Composition root, Flask app factory (`create_app`), blueprint registration, and Waitress WSGI runner (`main()`).
  * *Complexity & Improvements:* Clean dependency wiring.
  * *Missing Feature / Bug:* Channel timeout is hardcoded to 600s for SSE connections. Waitress multi-threaded server runs the worker thread in-process. If the app is run with multiple WSGI processes (e.g. gunicorn/waitress cluster), multiple uncoordinated background index pollers and workers would spawn.
* **[`src/gates/backtesting_adapter.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/backtesting_adapter.py) (40 lines):**
  * *Dead Code:* `BacktestPortfolioEngineAdapter` is an unused bridge between replay simulation and portfolio engine.
* **[`src/gates/cli.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/cli.py) (95 lines):**
  * *Functionality:* CLI utility (`screener-ops`) for SQLite backup, restore, health checks, single worker job iteration (`work-once`), and streaming lease status.
* **[`src/gates/composition.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/composition.py) (251 lines):**
  * *Functionality:* Central dependency injection container (`ApplicationServices.create`). Constructs all repositories, publishers, and job handlers.
  * *Complexity & Improvements:* Centralizes 24 worker job handlers in one dictionary.
* **[`src/gates/indicator_implementations.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/indicator_implementations.py) (80 lines):** Dispatches Python implementations for indicators when not expressed in pure Pandas TA.
* **[`src/gates/momentum_quality.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/momentum_quality.py) (22 lines):**
  * *Dead Code:* Passthrough re-export of `momentum_quality_feature_series` and `momentum_quality_features`.
* **[`src/gates/operations.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/operations.py) (60 lines):** `sqlite_backup`, `sqlite_restore`, and `sqlite_ready` integrity checks.
* **[`src/gates/payloads.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/payloads.py) (168 lines):**
  * *Dead Code:* Defines `BacktestPayload`, `FetchBarsPayload`, and `RebuildMultiYearPayload` which are unused. Only `RebuildRangePayload` and `RebuildIndicatorsPayload` are active.
* **[`src/gates/release_gates.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/release_gates.py) (94 lines):**
  * *Dead Code:* Contains one-off v3->v4 migration validation routines (`compare_execution_events`, `restore_drill`, `dashboard_visual_contract`, `next_tradable_session`). Zero references in application routes or CLI. Removable.
* **[`src/gates/repositories.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/repositories.py) (341 lines):**
  * *Functionality:* Gate-level `MarketRepository` inheriting from `MarketDataRepository` and `ReferenceDataRepository`. Resolves exit sessions and executes corporate action bar adjustments.
* **[`src/gates/runtime.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/runtime.py) (31 lines):** Environment configuration holder (`RuntimeConfig`).
* **[`src/gates/security.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/security.py) (20 lines):** `RedactingLogFilter` attached to the root logger to sanitize credentials.
* **[`src/gates/session_coverage.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/session_coverage.py) (91 lines):** Verifies that market bars exist for all Nifty 500 constituents across all completed exchange sessions.
* **[`src/gates/strategy_definitions.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/strategy_definitions.py) (15 lines) & [`src/gates/strategy_validation.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/strategy_validation.py) (35 lines):** Adapts indicator validation into strategy parsing.
* **[`src/gates/strategy_runtime.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/strategy_runtime.py) (189 lines):** Strategy runtime executing either compiled DAG graphs or legacy Python functions, seeds YAML definitions on startup.

---

#### Gate HTTP Blueprints (`src/gates/http/`)
* **[`actions.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/actions.py) (195 lines):** Proposal review endpoints: `/proposals`, `/proposals/<id>/approve`, `/reject`, `/amend`, `/bulk-decision`, `/manual`, `/midweek-stop`.
* **[`backtest.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/backtest.py) (57 lines):** Readback endpoints for backtest runs, walk-forward analyses, and factor attribution reports.
* **[`broker.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/broker.py) (82 lines):** Endpoints for creating orders, baskets, submitting orders to Kite, reconciling broker fills, and recording manual fills.
* **[`dashboard.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/dashboard.py) (54 lines):** Renders HTML views (`/`, `/actions`, `/pipeline`, `/rankings`, `/universe`, `/backtest`, `/settings`, `/logs`).
* **[`indicators.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/indicators.py) (23 lines):** Returns indicator catalog JSON specs.
* **[`kite_accounts.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/kite_accounts.py) (71 lines):** Broker account registration, login URL generation, request-token authentication, and holdings readback.
* **[`kite_auth.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/kite_auth.py) (138 lines):** Interactive browser OAuth flow for daily Zerodha Kite Connect login.
* **[`market.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/market.py) (300 lines):** Index quotes, coverage matrices, intraday stop-alert SSE streams, and bar queries.
* **[`operations.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/operations.py) (163 lines):**
  * *Critical Concurrency Flaw:* SSE streaming endpoint `/jobs/<id>/events` loops with `time.sleep(1)` inside the WSGI thread. Under Waitress, each streaming connection ties up 1 of the 8 available worker threads indefinitely until the job completes or the client disconnects!
* **[`pipeline.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/pipeline.py) (44 lines):** Multi-stage research pipeline submission, stage retry, and status readback.
* **[`portfolio.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/portfolio.py) (558 lines):**
  * *Complexity Issue:* `valuation()` (145 lines) performs inline queries to historical bars, trailing stops, ATR projections, Newton-Raphson XIRR calculations, and ledger event iterations directly inside the request handler. This should be refactored into a dedicated domain service.
* **[`positional_trend.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/positional_trend.py) (51 lines):** Endpoints to trigger daily signal builds and fetch signals.
* **[`reference.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/reference.py) (234 lines):** Readback and manual publish endpoints for sectors, macro indicators (VIX), market cap, and fundamentals.
* **[`research.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/research.py) (198 lines):** Readback for factor scores, percentiles, rankings, correlation matrices, and return anomalies.
* **[`strategies.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/strategies.py) (44 lines):** Strategy revision management and activation.
* **[`universe.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/universe.py) (66 lines):** Nifty 500 snapshot browsing and snapshot comparison.
* **[`wiki.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/http/wiki.py) (81 lines):** In-app documentation markdown renderer.

---

#### Gate Workflows (`src/gates/workflows/`)
* **[`backtesting.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/backtesting.py) (1,048 lines):**
  * *Functionality:* Coordinates historical simulation, stress testing, walk-forward analysis, and factor attribution.
  * *Complexity:* Massive class `BacktestJobs`. Methods `execute` (395 lines) and `_execute_positional_trend` (242 lines) duplicate substantial replay logic.
* **[`broker_orders.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/broker_orders.py) (442 lines):** Converts approved proposals to local order intents, validates against `ManagedRiskGuard`, and handles submit/reconcile lifecycles.
* **[`corporate_actions.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/corporate_actions.py) (527 lines):** Detects splits and bonuses from NSE feeds, parses ratios, verifies historical price gaps against Kite, and atomically adjusts stored bars.
* **[`index_poller.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/index_poller.py) (169 lines):** Polling loop that queues index quote fetch jobs during active NSE market hours (9:15 AM - 3:30 PM IST).
* **[`intraday_stream.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/intraday_stream.py) (114 lines):** Leased state machine for WebSocket supervisor.
* **[`liquidity_universe.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/liquidity_universe.py) (155 lines):** Filters top 500 stocks by turnover and volume.
* **[`live_quote_stream.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/live_quote_stream.py) (97 lines):** Bridges `KiteStreamingProvider` to `LiveQuotes` and `IntradayStopAlerts`.
* **[`managed_risk.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/managed_risk.py) (247 lines):** Hard circuit-breaker preventing order submission if single-stock weight > 10%, ADV > 5%, or available cash is exceeded.
* **[`market_ingestion.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/market_ingestion.py) (85 lines):** Raw snapshot publication followed by normalized bar ingestion.
* **[`market_jobs.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/market_jobs.py) (700 lines):** Implements Kite API fetch handlers for historical bars, bulk bars, index quotes, and instrument sync.
* **[`market_refresh.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/market_refresh.py) (286 lines):** Schedules refresh jobs only for missing historical intervals.
* **[`pipeline_preparation.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/pipeline_preparation.py) (207 lines):** Sequentially coordinates Nifty 500 download, instrument sync, corporate action detection, and bar refreshes.
* **[`portfolio_actions.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/portfolio_actions.py) (1,818 lines):**
  * *Critical Complexity Hotspot:* The largest file in the codebase. Method `generate()` is **707 lines with 161 branch statements**! It handles ranking lookup, bar validation, sector limits, macro VIX filters, drawdown circuit-breakers, market-cap sizing, fundamental constraints (EPS, D/E), stop-loss pricing, cash allocations, and JSON serialization in one giant routine.
  * *Recommendation:* Must be broken down into composable pipeline filter stages: `UniverseFilter`, `FundamentalFilter`, `MacroRegimeFilter`, `PositionSizer`, `ProposalEmitter`.
* **[`portfolio_sync.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/portfolio_sync.py) (266 lines):** Reconciles external broker holdings with local ledger accounts.
* **[`positional_trend.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/positional_trend.py) (188 lines):** Computes daily positional trend breakouts and publishes signal artifacts.
* **[`positional_trend_backtest_inputs.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/positional_trend_backtest_inputs.py) (313 lines):** Composite loader for backtest OHLCV data and benchmark index series.
* **[`research.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/research.py) (1,189 lines):** Vectorized calculation engine for multi-year strategy ranges. Generates features, percentiles, daily scores, and weekly rankings.
* **[`research_pipeline.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/research_pipeline.py) (415 lines):** Durable state machine driving multi-stage pipeline execution (`PREPARATION` -> `FACTOR_CALCULATION` -> `RESEARCH_RANGE`).
* **[`trading_calendar.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/trading_calendar.py) (88 lines):** Calendar calculations derived from actual observed NSE trading sessions.
* **[`universe.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/gates/workflows/universe.py) (212 lines):** Downloads and archives Nifty 500 constituents and identifies universe dropouts.

---

### D. Frontend & UI (`templates/` & `static/`)

* **Templates (`templates/`):**
  * `base.html`: Common shell with sidebar navigation, index ticker carousel, and modal container.
  * `home.html`: Portfolio overview, account valuation summary, active positions, and recent ledger activity.
  * `actions.html`: Interactive proposal approval, individual stock decision buttons, risk preview, and manual fill modal.
  * `pipeline.html`: Interactive pipeline execution progress bars, stage status, and worker controls.
  * `rankings.html`: Strategy ranking table with factor breakdowns.
  * `backtest.html`: Backtest configuration, equity curves, drawdown charts, and metrics summary.
  * `logs.html`, `settings.html`, `universe.html`: Minimal utility views.
  * `ui-guide.html` & `wiki.html`: In-app operator documentation.
* **Client JavaScript (`static/js/`):**
  * `common.js`: Fetch wrapper with automatic error toast handling.
  * `index_carousel.js`: Real-time index ticker sparkline generator.
  * `actions.js` (183 lines): Action proposal review and decision submitter.
  * `pipeline.js` (97 lines): Polls active pipeline stages and renders progress.
  * `portfolio.js` (131 lines): Account valuation and trade recording.
  * `backtest.js` (168 lines): Triggers backtest runs and renders metrics tables.
  * `rankings.js`, `settings.js`, `universe.js`, `logs.js`, `wiki.js`: Vanilla DOM handlers.
* **Styling (`static/css/carbon-emerald.css`):**
  * Custom dark-themed CSS design system ("Carbon & Emerald") using CSS custom properties. Clean and modern typography, but several views (`logs.html`, `settings.html`) lack responsive polish.

---

### E. Configuration & Operational Files

* **[`run.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/run.py):** Main entry point; invokes `src.gates.app.main()`.
* **[`pyproject.toml`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/pyproject.toml):**
  * Python `>=3.13` requirement.
  * Dependencies: `requests`, `kiteconnect`, `flask`, `pandas`, `pandas-ta`, `PyYAML`, `waitress`, `typing-extensions`, `markdown-it-py`.
  * *Unused dependency:* `typing-extensions` is specified as a direct dependency but never imported in source files (Python 3.13 standard `typing` covers all usages).
* **[`Makefile`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/Makefile):** Useful shortcuts for lint, test, type, security, run, and backup.
* **[`strategies/momentum.yml`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/strategies/momentum.yml) & [`strategies/positional_trend_following.yml`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/strategies/positional_trend_following.yml):**
  * Declarative YAML strategy definitions. Well-specified factors, parameter boundaries, and exit rules.
* **`.gitignore`:** Correctly ignores `.db`, `.sqlite`, `instance/`, `local_secrets.py`, `access_token.txt`.

---

## 3. High-Priority Issues, Bugs, and Storage Bloat

### 1. Severe Class Shadowing Bug in `src/domains/reference_data/api.py`
In `src/domains/reference_data/api.py`:
```python
# Line 339:
@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    ex_date: date
    action_type: str
    ratio: str | None = None
    ...

# Line 472 (Overwrites the class!):
class CorporateAction(NamedTuple):
    action_type: str
    ex_date: date
    ratio_from: Decimal
    ...
```
Any caller importing `CorporateAction` from `src.domains.reference_data` receives the `NamedTuple` variant instead of the dataclass, causing runtime attribute mismatches. The second class must be renamed to `CorporateActionAdjustment` or `ParsedCorporateAction`.

### 2. Massive Disk Storage Bloat in `instance/` (13.2 GB total)
An inspection of the user's `instance/` folder reveals:
* `instance/stock_screener_legacy_20261003.db`: **9.65 GB**! This is an obsolete pre-migration database snapshot left in the instance directory.
* `instance/stock_screener.db`: **3.61 GB**. Inside this database:
  * `market_indicators`: 1.07 GB (1,093,464 rows)
  * `research_percentiles`: 857 MB + 840 MB index (1.7 GB total!)
* **Recommendation:**
  * Archive or remove `stock_screener_legacy_20261003.db`.
  * The `research_percentiles` table stores full JSON dumps for daily percentiles. Compacting historical percentiles to weekly or compressing JSON blobs will cut database size by ~70%.

### 3. WSGI Thread Exhaustion via SSE `time.sleep()` in `src/gates/http/operations.py`
The `/api/operations/jobs/<job_id>/events` endpoint uses `stream_with_context` with a synchronous `time.sleep(1)` loop:
```python
while True:
    events = jobs.events_after(job_id, after)
    ...
    time.sleep(1)
```
Waitress defaults to 8 worker threads. If a user opens 8 browser tabs streaming job progress, **all Waitress worker threads become permanently occupied**, completely freezing the entire web application for all other HTTP requests!
* **Fix:** Use short-polling on the client side, or switch streaming endpoints to non-blocking generators or WebSockets.

### 4. Overly Complex Monolith: `src/gates/workflows/portfolio_actions.py`
At 1,818 lines, `portfolio_actions.py` (specifically `generate()`, 707 lines) has become an unmaintainable catch-all for all portfolio pre-conditions, market cap weighting, fundamental screening, and order sizing. It violates the Single Responsibility Principle and makes unit testing individual sizing rules very difficult.

---

## 4. Dead Code & Removable Components

The following modules and classes are either completely unused or redundant and can be safely removed or consolidated:

| File / Component | Lines | Reason for Removal / Consolidation |
|---|---|---|
| `src/domains/reference_data/api.py` (Duplicate `CorporateAction`) | ~25 | Duplicate class definition shadowing the primary dataclass. |
| `src/domains/backtesting/event_study.py` | 219 | Unused event-study calculation module; no API or UI consumer. |
| `src/domains/strategies/positional_trend_comparison.py` | 77 | `pandas_ta_features` has zero callers across the application. |
| `src/domains/strategies/ranking_patterns.py` | 190 | Unused dispatch pattern; strategy calculations are called directly. |
| `src/gates/release_gates.py` | 94 | Obsolete v3->v4 cutover parity checks with no callers in runtime or CLI. |
| `src/gates/backtesting_adapter.py` | 40 | Unused adapter class `BacktestPortfolioEngineAdapter`. |
| `src/gates/momentum_quality.py` | 22 | Trivial 2-line passthrough re-exporting domain functions. |
| `src/gates/payloads.py` (`BacktestPayload`, `FetchBarsPayload`, `RebuildMultiYearPayload`) | ~80 | Dead payload dataclasses with no callers. |
| `src/platform_kernel/contracts.py` (`VersionedReference`, `CommandMetadata`) | ~30 | Declared but never used in any domain or workflow. |
| `instance/stock_screener_legacy_20261003.db` | - | 9.65 GB obsolete database file taking up massive disk space. |
| `instance/run_one_pipeline_job.py` | 218 | Ad-hoc scratch script sitting in data directory. |

---

## 5. Missing Features for a Complete Stock Screener & Portfolio App

To elevate this application from a local CLI/script-heavy tool into a first-class production screener and portfolio management suite, the following features should be implemented:

### 1. Interactive Screener & Custom Filter Builder
* **Current State:** Only 2 pre-baked YAML strategies (`momentum`, `positional_trend_following`).
* **Missing Feature:** A visual query builder on the UI allowing operators to create custom screeners on the fly (e.g. *RSI(14) < 35 AND Close > 200 EMA AND Traded Value > 10 Cr*) without having to write YAML files and restart the server.

### 2. Interactive Charts (TradingView Lightweight Charts)
* **Current State:** The UI only displays static data tables and small SVG sparklines.
* **Missing Feature:** Clicking any stock symbol in Rankings or Actions should open an interactive candlestick chart displaying:
  * Daily OHLCV candles.
  * Supertrend & Donchian channel overlays.
  * Entry / Exit marker badges from the strategy proposal.
  * ATR trailing stop lines.

### 3. Corporate Action Dividend Tracking
* **Current State:** The app handles stock splits and bonus issues via price adjustments in `market_bars`.
* **Missing Feature:** Cash dividends are completely ignored! In an event-sourced portfolio ledger, dividends must be automatically imported or credited to the account's cash balance upon the ex-dividend date to ensure accurate XIRR performance.

### 4. GTT (Good-Till-Triggered) Order Integration
* **Current State:** Stop-loss orders are handled via simulated intraday alerts or manual AMO orders.
* **Missing Feature:** Zerodha Kite natively supports GTT (Good-Till-Triggered) OCO (One-Cancels-Other) stop-loss orders. Integrating GTT placement via Kite Connect API upon fill confirmation would automate capital protection without requiring the app to be streaming 24/7.

### 5. Export Functionality (CSV / Excel / PDF)
* **Current State:** Data is only viewable in the browser HTML tables.
* **Missing Feature:** One-click CSV/Excel export buttons for:
  * Strategy Rankings (with all factor percentiles).
  * Portfolio Journal & Tax Gain/Loss report (for ITR tax filing).
  * Backtest trade logs.

### 6. Automated Database Vacuum & Data Retention Policy
* **Current State:** `instance/stock_screener.db` has grown to 3.6 GB because high-frequency percentile matrices are never cleaned up.
* **Missing Feature:** Automated retention policy (e.g., pruning raw intermediate indicator node caches older than 90 days, vacuuming SQLite WAL files).

---

## 6. Actionable Implementation Roadmap & Status

1. **Step 1: Clean Up & Immediate Bug Fixes [COMPLETED]**
   * [x] Delete `instance/stock_screener_legacy_20261003.db*` freeing up 10.1 GB of disk space.
   * [x] Delete ad-hoc scratch script `instance/run_one_pipeline_job.py` and old `.log` files.
   * [x] Remove dead code modules (`src/gates/release_gates.py`, `src/domains/strategies/positional_trend_comparison.py`, `src/domains/backtesting/event_study.py`).
   * [x] Prune dead payload dataclasses (`FetchBarsPayload`, `BacktestPayload`, `RebuildMultiYearPayload` in `src/gates/payloads.py`).
   * [x] Prune dead value objects (`VersionedReference`, `CommandMetadata`, `AggregateVersion` in `src/platform_kernel/contracts.py`).
   * [x] Trim 60 blank trailing lines in `src/domains/market_data/repository.py`.
   * [x] Fix loop variable closure bug (Ruff B023) in `src/gates/workflows/research.py`.
   * [x] Fix Waitress WSGI thread starvation in `src/gates/http/operations.py` by bounding SSE streaming loop and adding `retry: 1000\n\n` header.
   * [x] Increase SQLite `busy_timeout` to 30,000ms in `src/platform_kernel/sqlite.py`.
   * [x] Configure `--basetemp=.pytest_tmp_scan` in `pyproject.toml` to prevent Windows Temp permissions issues.
   * [x] Verify 100% test pass rate (451 passed) and clean Ruff linter checks across `src/`.

2. **Step 2: Database Storage & Query Index Optimization [COMPLETED]**
   * [x] Added composite index `catalog_artifacts_category_status_created` on `catalog_artifacts(category, status, created_at DESC)` in `src/domains/artifacts/catalog.py` (migration v2).
   * [x] Added covering index `market_bars_date_instrument` on `market_bars(as_of_date, instrument_id)` in `src/domains/market_data/schema.py` (migration v2).
   * [x] Added index `ops_job_events_job_event_index` on `ops_job_events(job_id, event_id)` in `src/domains/operations/jobs.py` (migration v2).
   * [x] Added index `research_percentile_snapshots_lookup` on `research_percentile_snapshots(input_fingerprint, as_of_date)` and `research_percentiles_date` on `research_percentiles(as_of_date)` in `src/domains/research/repository.py` (migration v2).
   * [x] Implemented `prune_percentiles(before_date)` in `ResearchRepository` for purging intermediate percentile matrices.
   * [x] Added `sqlite_vacuum(database)` in `src/gates/operations.py` for reclaiming reclaimed pages.
   * [x] Added `vacuum-sqlite` and `prune-percentiles` commands to the `screener-ops` CLI in `src/gates/cli.py`.
   * [x] Verified and applied all migrations live to `instance/stock_screener.db`.
   * [x] Verified 100% test pass rate (453 passed) and clean Ruff linter checks.

3. **Step 3: Refactor Monolithic Workflows [NEXT]**
   * Decompose `ActionJobs.generate()` in `portfolio_actions.py` into a composable pipeline (`UniverseFilter`, `FundamentalFilter`, `MacroRegimeFilter`, `PositionSizer`, `ProposalEmitter`).
   * Extract valuation logic from `portfolio.py` HTTP route into a dedicated `ValuationService`.

4. **Step 4: Frontend & Feature Enhancements**
   * Integrate TradingView Lightweight Charts in `rankings.html` and `actions.html`.
   * Add CSV export for rankings, trade journal, and backtest results.
   * Implement Kite GTT order placement workflow for automated stop-loss protection.
   * Track cash dividends in portfolio ledger.

