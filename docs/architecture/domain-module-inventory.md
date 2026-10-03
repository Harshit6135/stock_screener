# Source and domain ownership inventory

Historical ownership inventory for the `src/domains/` and `src/gates/` restructure. The current file-by-file source listing is generated in `docs/src-file-inventory.md`; migration outcomes are recorded in the log below.

## Proposed structural rules

- `src/platform_kernel/` remains the shared, domain-neutral foundation.
- Existing domain packages move as whole packages under `src/domains/`; no extra grouping level is added inside each domain.
- `src/gates/` owns HTTP/CLI entry adapters, dependency composition, durable job handlers, and workflows that coordinate multiple domains.
- A domain may depend on the platform kernel and its own modules. Cross-domain workflows must be expressed through gates or explicit contracts, not direct domain imports.
- Within each domain, use a consistent responsibility vocabulary where applicable: `api.py` for public domain contracts, `services.py` for domain operations, `repository.py` for persistence adapters, and `providers.py` for external data/broker adapters. Do not create empty files where a responsibility does not exist.

## Existing top-level packages and proposed destination

| Current package | Proposed destination | Initial responsibility |
| --- | --- | --- |
| `src/platform_kernel` | stays at `src/platform_kernel` | shared contracts, value types, artifact storage primitives; no domain behavior |
| `src/market_data` | moved to `src/domains/market_data` | bars, providers, market history, calendars, market snapshots |
| `src/reference_data` | moved to `src/domains/reference_data` | instrument/reference snapshots, aliases, calendars, corporate-action reference types |
| `src/indicators` | retired Step 93; implementation in `src/domains/indicators` | indicator contracts, registry, DAG, custom feature calculations |
| `src/strategies` | retired Step 93; implementation in `src/domains/strategies` | strategy definitions, ranking, runtime contracts and signals |
| `src/backtesting` | Removed Step 78; `src/domains/backtesting` owns replay models/engine and run records | Internal callers use the curated domain package |
| `src/portfolio_engine` | moved to `src/domains/portfolio_engine` | portfolio decision rules and policy |
| `src/portfolio_accounting` | moved to `src/domains/portfolio_accounting` | fills, accounting events and projections |
| `src/execution_gateway` | retired in Step 94 | order persistence moved to execution; cross-domain broker orchestration moved to gates |
| `src/application` | retired in Step 92 | its former route/composition/workflow and domain responsibilities are now assigned to gates or domain packages |

## Gateways required by current cross-domain workflows

| Current code path | Current interaction | Proposed ownership |
| --- | --- | --- |
| `gates/workflows/portfolio_actions.py` | combines market, positional strategy, research, ledger, portfolio decisions, accounting and publication | proposal persistence belongs to `domains/portfolio_engine`; gate workflow owns cross-domain coordination |
| `gates/workflows/backtesting.py` | coordinates replay, market/research/corporate-action services and publication through public APIs | run storage and replay engine belong to `domains/backtesting`; research and Strategy 4 input-loader seams remain to review |
| `gates/workflows/corporate_actions.py` | market history, corporate-action lifecycle, ledger, indicator cache and publication | gate workflow coordinates market data, accounting and indicators; pure corporate-action types/rules are a candidate for extraction after function audit |
| `gates/workflows/research_pipeline.py`, `pipeline_preparation.py` | coordinates strategies, market refresh, universe, corporate actions and research | gates job/workflow orchestration |
| `gates/workflows/portfolio_sync.py` | coordinates broker account, ledger, market repository and portfolio inputs | gate workflow coordinates execution and portfolio domains |
| `domains/execution/order_repository.py`, `gates/workflows/broker_orders.py` | order state is execution-owned; market membership and cross-domain approval/risk work are gate-owned | Completed Step 94 |
| `domains/indicators/`, `domains/strategies/` | independent feature and strategy signal APIs | consolidated from legacy roots; gate runtime composes them without domain-to-domain imports |

## Domain dependency boundary status

The recursive architecture check currently reports zero domain-to-application, domain-to-gate, cross-domain, or kernel violations. The former findings below have been retired by the owner moves recorded in Steps 72–94; the exact live boundary rule is maintained in `tests/architecture/test_import_boundaries.py`.

| Former importing module | Former dependency | Resolution |
| --- | --- | --- |
| `domains/execution/order_repository.py`, `gates/workflows/broker_orders.py` | schema/events remain execution-owned; gate composes market, account, portfolio, and risk APIs | Completed Step 94 |
| `domains/execution/accounts.py` | Strategy IDs enter through the constructor from the public strategies contract; no direct domain import remains | Completed Step 89 |
| `indicators/custom/__init__.py` | application positional-trend feature | Legacy indicators root removed in Step 93; active indicator/strategy APIs are domain-owned |

## Mixed-responsibility file review

| Current file | Responsibilities found in its symbols | Proposed treatment |
| --- | --- | --- |
| `application/market_repository.py` | `gates/repositories.py` plus domain-owned repositories | Five-line compatibility facade removed Step 74; composite queries stay in gates, and table writes/read models are split by owner. |
| `gates/workflows/portfolio_actions.py` (moved Step 76) | proposal generation, policy comparison, risk projections, manual/amend flows, artifact/ledger/market coordination | gate-owned coordinator; proposal persistence and lifecycle reads live in portfolio_engine |
| `gates/workflows/research.py` | market/runtime input loading, artifact publication, and cross-domain research job coordination; persistence moved Step 82 and pure ranking/anomaly calculations moved Step 83 | coordinator moved from application in Step 84; keep reusable calculations and research table SQL in the research domain |
| `application/market_jobs.py` (485 lines) | Kite client and market fetches, provider history, instrument sync, index quotes and stop-alert dispatch | moved to `gates/workflows/market_jobs.py`; durable handler and cross-domain coordination |
| `application/corporate_actions.py` (618 lines) | provider date/ratio parsing, event classification/detection, adjustment math, ledger updates, publication, cache invalidation | split parsing/pure adjustment logic from cross-domain event processing; the latter is a gate workflow |
| `gates/workflows/backtesting.py` | request validation, replay dispatch, stress/walk-forward/attribution and cross-domain coordination moved Step 79; run persistence extracted Step 77 | run index and replay engine in `domains/backtesting`; further calculations and legacy loader/service seams remain candidates |
| `application/market_web.py` (304 lines) | market routes plus corporate-action, quote, refresh and stream endpoints | split into gate route modules by external resource; routes remain adapters and call gate use cases |
| `gates/strategy_runtime.py` | cross-domain strategy definitions, indicator DAG execution, and implementation registry | moved to the interaction layer in Step 81; canonical identifier rules remain in `domains/strategies/identity.py` |
| `domains/strategies/positional_trend_backtest.py`, `gates/workflows/positional_trend_backtest_inputs.py` | Strategy 4 policy/replay and CSV/market-history input assembly | Simulation is strategies-owned; composite readers are gate-owned pending further repository API adoption; CLI entry belongs in tools |
| `application/index_poller.py` | quote polling state, scheduling, exchange-open checks and background thread | market quote polling belongs to market-data service; generic thread lifecycle/job scheduling belongs in gates |
| `application/kite_auth.py` | credentials/config loading, Kite client protocol and token-file login lifecycle | move broker-specific auth to `domains/execution`; keep environment/config assembly at gates |
| `application/liquidity.py` | JSON validation/decoding plus mapping domain inputs to liquidity snapshot and publishing it | decoding/request boundary belongs in gates; universe calculation stays in `domains/reference_data` |
| `application/portfolio_web.py` | Flask request/response adapter and money/input validation around portfolio services | remain in gates; move reusable validation/calculation to portfolio domain contracts |
| `application/composition.py` | constructs every store/domain service and registers all durable job handlers | remain the gate composition root; later reduce it into small provider functions only if wiring becomes hard to trace |

## Application module-by-module ownership proposal

The initial inventory contained 62 application modules; 51 remain after moving SQLite, session coverage, ranking patterns, portfolio performance, node cache, operations, release gates, strategy definitions, and the strategies, dashboard, and reference HTTP adapters.

### Migration progress

| File moved | New location | Import updates |
| --- | --- | --- |
| `application/sqlite.py` | `platform_kernel/sqlite.py` | Updated 31 source, test, and tool files to import `src.platform_kernel.sqlite`. |
| `application/session_coverage.py` | `gates/session_coverage.py` | Updated market refresh, pipeline preparation, and coverage tests; benchmark symbols are now injected. |
| `application/ranking_patterns.py` | `domains/strategies/ranking_patterns.py` | Moved with ranking tests to the strategies domain. |
| `application/portfolio_performance.py` | `domains/portfolio_accounting/portfolio_performance.py` | Moved with its focused test; uses a ledger protocol rather than importing execution. |
| `application/node_cache.py` | `domains/indicators/node_cache.py` | Cache and focused test now mirror the indicators domain. |
| `application/operations.py` | `gates/operations.py` | Moved with operations and CLI tests to gates. |
| `application/release_gates.py` | `gates/release_gates.py` | Moved with release-gate and worker tests to gates. |
| `application/strategy_definitions.py` | `gates/strategy_definitions.py` | Updated application/test imports; focused test moved to `tests/gates/test_strategy_definitions.py`. |
| `application/strategies_web.py` | `gates/strategies_web.py` | Updated `run.py` blueprint registration; no dedicated test module exists. |
| `application/dashboard_web.py` | `gates/dashboard_web.py` | Updated `run.py`; app integration test moved to `integration_tests/gates/test_dashboard_web.py`. |
| `application/reference_web.py` | `gates/reference_web.py` | Updated `run.py` and test imports; both API tests moved to `integration_tests/gates/`. |
| `indicators/registry.py` | `domains/indicators/registry.py` | Updated source and test imports; no dedicated registry test module exists. |
| `indicators/dag.py` | `domains/indicators/dag.py` | Updated source/test imports; focused unit test moved to `tests/domains/indicators/test_dag_executor.py`. |
| `indicators/api.py` | `domains/indicators/api.py` | Updated the legacy facade and test imports; existing coverage remains in broader research/strategy tests. |
| `indicators/custom/relative_strength.py` | `domains/indicators/relative_strength.py` | Flattened custom calculations into the indicators domain; updated registry and backtest code-hash references. |
| `indicators/custom/momentum_quality.py` | `domains/indicators/momentum_quality.py`, `domains/strategies/momentum_quality.py`, `gates/momentum_quality.py` | Split raw indicator calculation, factor scoring, and cross-domain composition; focused integration test moved to `integration_tests/gates/test_momentum_quality.py`. |


Destinations below are provisional. “Split” means assign functions/classes individually after reviewing call graphs; it is not an instruction to move the entire current file. Domain destinations are siblings directly under `src/domains/<domain>/`, following the existing package layout.

| Current module | Proposed owner | Notes / function-level split candidate |
| --- | --- | --- |
| `application/__init__.py` | removed | Empty compatibility package removed in Step 92 after repository-wide caller audit. |
| `gates/workflows/portfolio_actions.py` | gates workflow | Proposal storage moved to `domains/portfolio_engine/proposal_store.py` Step 75; remaining orchestration crosses market, research, accounting, execution, and artifacts. |
| `application/actions_web.py` | gates HTTP | Request/response adapter for action workflows. |
| `gates/workflows/backtesting.py` | gates workflow | `BacktestRunStore` and replay engine are in `domains/backtesting`; two transitional legacy imports remain. |
| `application/backtest_web.py` | gates HTTP | Request/response adapter. |
| `application/broker_web.py` | gates HTTP | Request/response adapter for execution domain. |
| `application/catalog.py` | artifacts | Unused compatibility facade removed after catalog ownership moved to `domains/artifacts`. |
| `application/cli.py` | `gates/cli.py` | Unused re-export removed Step 73; configured CLI imports gates directly. |
| `application/composition.py` | gates composition | Sole cross-domain construction/wiring point; keep as traceable root. |
| `application/corporate_actions.py` | split: reference-data/market rules + gates workflow | Date/ratio parsing, classification and adjustment math are domain candidates; broker verification, ledger, cache invalidation and publication coordination stay in gates. |
| `gates/dashboard_web.py` | gates HTTP | Dashboard route and template adapter. |
| `application/exchange_calendar.py` | reference data | Persisted trading-session calendar; reconcile with existing `reference_data.ExchangeCalendar` and keep one canonical contract. |
| `application/index_poller.py` | split: market data + gates | Quote/polling state and market-open semantics belong with market data; background thread lifecycle/job submission belongs in gates. |
| `application/indicators_web.py` | gates HTTP | Adapter for indicator catalogue/calculation API. |
| `application/ingestion.py` | market data | Provider-bar normalization/publication path; ensure no gate-only dependencies remain. |
| `application/intraday_alerts.py` | split: execution/market domain + gates | Pure stop/alert eligibility and state model may belong to execution; dispatch, job context, and artifact publication coordination stay in gates. |
| `application/intraday_stream.py` | split: market data + gates | Stream lease/state contract versus worker/process lifecycle. |
| `application/jobs.py` | `domains/operations/jobs.py` | Unused re-export removed Step 73; package-level exports remain domain-backed. |
| `application/kite_accounts_web.py` | gates HTTP | Adapter for execution account workflows. |
| `domains/execution/accounts.py` | execution | `KiteAccounts` moved from the legacy gateway in Step 89; allowed strategy IDs are injected through a constructor contract. |
| `application/kite_web.py` | gates HTTP | Login/session routes. |
| `application/liquidity.py` | split: reference data + gates | Payload decoding/validation and artifact publication at gates; mapping to `LiquidityUniversePolicy` and pure universe generation in reference data. |
| `application/live_quotes.py` | market data / execution contract | Quote store and stream adapter; separate generic quote state from Kite-specific stream/provider connection. |
| `gates/workflows/managed_risk.py` | portfolio_engine and execution | Cross-domain risk guard; reservation persistence now belongs to `domains/portfolio_engine/risk_reservations.py`, while the gate keeps the shared ledger/market/config transaction. |
| `application/market_jobs.py` | split: market data + gates | Provider calls and market normalization belong with market data; durable job handlers, alert dispatch and multi-service orchestration stay in gates. |
| `application/market_refresh.py` | split: market data + gates | Refresh planning policy versus JobStore scheduling/reconciliation orchestration. |
| `application/market_repository.py` | market data | Split instrument/universe, price/coverage/index, and corporate-action persistence into sibling repository modules; retain one migration/schema ownership strategy. |
| `application/market_web.py` | gates HTTP | Split routes by resource (market, corporate actions, quotes/stream, refresh) while keeping Flask concerns in gates. |
| `domains/indicators/node_cache.py` | indicators | Moved in step 5; persistent cache uses the shared platform SQLite layer. |
| `application/nse_client.py` | market data / reference data | NSE transport/download adapter; assign response parsing to the domain that owns each payload. |
| `gates/operations.py` | gates | SQLite backup/restore/readiness utilities used by CLI and release checks. |
| `gates/payloads.py` | gate request and job payload parsing | Moved from application in Step 84; move only independently reusable business policy to domain APIs. |
| `gates/workflows/research_pipeline.py` | gates workflow | Job handler and pipeline lifecycle coordinating strategy and market services. |
| `application/pipeline_preparation.py` | gates workflow | Multi-domain preparation/synchronization coordinator. |
| `application/pipeline_web.py` | gates HTTP | Request/response adapter. |
| `application/portfolio_sync.py` | gates workflow | Coordinates broker accounts, ledger and market data; no domain-to-domain imports. |
| `application/portfolio_web.py` | gates HTTP | Request/response adapter; move reusable typed validation to portfolio contracts only if domain-owned. |
| `domains/strategies/positional_trend_backtest.py`, `gates/workflows/positional_trend_backtest_inputs.py` | strategies + gates input adapter | Strategy 4 policy/replay moved Step 80; database/CSV input assembly moved to the gate and is a candidate for public repository APIs. |
| `application/positional_trend_jobs.py` | gates workflow | Durable job handlers coordinating strategy and market-data services. |
| `application/positional_trend_web.py` | gates HTTP | Request/response adapter. |
| `application/positional_trend.py` | `domains/strategies/positional_trend.py` | Unused re-export removed Step 73; calculation owner already resides in strategies. |
| `domains/execution/streaming_provider.py` | execution | Account-scoped Kite tick adapter moved from application in Step 87; stream process lifecycle and quote/alert coordination remain gate-owned. |
| `application/publication.py` | artifacts | Unused compatibility facade removed after publication ownership moved to `domains/artifacts`. |
| `domains/strategies/ranking_patterns.py` | strategies | Moved in step 1; ranking pattern implementations and selector. |
| `gates/reference_web.py` | gates HTTP | Request/response adapter. |
| `gates/release_gates.py` | gates/release tooling | Moved in step 3; operational parity/restore checks, not a product domain. |
| `gates/workflows/research.py` | gates workflow + public research/indicator/strategy APIs | Research schema and table persistence moved to `domains/research/repository.py` in Step 82; pure ranking/anomaly calculations moved to `domains/research/calculations.py` in Step 83; workflow coordinator moved here in Step 84. |
| `application/research_web.py` | gates HTTP | Request/response adapter. |
| `application/runs.py` | split: backtesting + gates | Backtest result mapping belongs with backtesting; publication call remains a gate/storage operation. |
| `application/runtime.py` | gates configuration | Environment/config loading only; no domain policy. |
| `application/security.py` | `platform_kernel/security.py`, `gates/security.py` | Unused re-export removed Step 73; implementation owners already exist. |
| `gates/strategies_web.py` | gates HTTP | Request/response adapter. |
| `gates/strategy_definitions.py` | gates | Persistence-backed YAML/revision workflow validating strategy definitions against the indicator domain. |
| `gates/strategy_runtime.py` | gates runtime | StrategyRuntime moved in Step 81; strategy IDs and definitions are domain-owned, while indicator execution is consumed through the public indicators API. |
| `application/universe_jobs.py` | split: reference/market data + gates | CSV provider parsing and exit/universe domain policy versus durable job orchestration. |
| `application/universe_web.py` | gates HTTP | Request/response adapter. |
| `application/web.py` | gates HTTP | Generic durable-job HTTP/SSE adapter. |
| `application/wiki_web.py` | gates HTTP | Documentation page adapter. |
| `application/worker.py` | `domains/operations/worker.py` | Unused re-export removed Step 73; package-level exports remain domain-backed. |

The removed application YFinance adapter was not included: repository-wide search found no callers, and the documented YFinance enrichment path had already been retired. The `yfinance` provenance strings in fixtures are data labels, not imports of the adapter.

## Live Python source inventory

The earlier inline AST listing was removed because repeated owner moves made it stale. The current import/symbol inventory is regenerated from the live worktree at [`docs/src-file-inventory.md`](../src-file-inventory.md). Current ownership and exact migration status are in [`restructure-migration-manifest.md`](restructure-migration-manifest.md); the module-by-module candidate map above remains the planning reference.

## Migration log

### Step 5 — indicator node cache

- Moved `src/application/node_cache.py` to `src/domains/indicators/node_cache.py`.
- Updated application composition and corporate-action callers plus DAG/corporate-action tests to import the domain API.
- Moved the dedicated cache test to `tests/domains/indicators/test_node_cache.py`.
- AST parsing succeeded for the module, callers, and test. Tests were not run.

### Step 6 — strategy definitions

- Moved `src/application/strategy_definitions.py` to `src/gates/strategy_definitions.py`; the module coordinates persisted strategy revisions with indicator validation APIs.
- Updated all application and test imports to `src.gates.strategy_definitions`.
- Moved the dedicated module test to `tests/gates/test_strategy_definitions.py`; broader phase and integration tests remain in place with updated imports.
- Static AST parsing and stale-path checks passed. Tests were not run.

### Step 7 — strategies HTTP adapter

- Moved `src/application/strategies_web.py` to `src/gates/strategies_web.py`.
- Updated `run.py` to register the blueprint from its new location.
- No dedicated test module existed to relocate.
- Static AST parsing and stale-path checks passed. Tests were not run.

### Step 8 — dashboard HTTP adapter

- Moved `src/application/dashboard_web.py` to `src/gates/dashboard_web.py`.
- Updated `run.py` to register the dashboard blueprint from `src.gates`.
- Moved the app-level dashboard integration test to `integration_tests/gates/test_dashboard_web.py` and added `integration_tests` to pytest discovery.
- Static AST parsing and stale-path checks passed. Tests were not run.

### Step 9 — reference HTTP adapter

- Moved `src/application/reference_web.py` to `src/gates/reference_web.py`; the module exposes reference reads and snapshot publication over HTTP.
- Updated `run.py` and test imports to use `src.gates.reference_web`.
- Moved both route/repository integration test modules to `integration_tests/gates/` with their existing `test_` basenames.
- Static AST parsing and stale-path checks passed. Tests were not run.

### Step 10 — indicator registry

- Moved `src/indicators/registry.py` to `src/domains/indicators/registry.py`; the approved catalogue and pandas_ta adapter are indicator-domain responsibilities.
- Updated direct imports in source and tests, including the existing DAG module’s registry dependency.
- No dedicated registry test module existed; existing DAG/strategy tests retain their basenames and locations until their corresponding source modules move.
- Static AST parsing and stale-path checks passed. Tests were not run.

### Step 11 — indicator DAG engine

- Moved `src/indicators/dag.py` to `src/domains/indicators/dag.py`; graph validation, hashing, and vectorized execution remain one indicator-domain responsibility.
- Moved its focused unit test to `tests/domains/indicators/test_dag_executor.py`.
- Updated source and test imports, and retained the legacy `src.indicators` package facade while the remaining indicator modules move.
- Updated the `src.domains.indicators` public exports and source inventory.
- Static AST parsing and stale-path checks passed. Tests were not run.

### Step 12 — indicator definitions and feature API

- Moved `src/indicators/api.py` to `src/domains/indicators/api.py`; revisions, configurations, feature values, and snapshots are indicator-domain contracts.
- Updated the legacy `src.indicators` facade and existing test imports to use the domain API.
- Added the API types and calculation function to the public exports of `src.domains.indicators`.
- Existing tests combine indicator API behavior with strategy/research assertions; no unrelated mixed test file was moved.
- Static AST parsing and stale-path checks passed. Tests were not run.

### Step 13 — relative-strength calculations

- Moved `src/indicators/custom/relative_strength.py` to `src/domains/indicators/relative_strength.py`, keeping indicator calculations at the domain root.
- Updated the custom implementation registry and the backtest code-revision input path.
- Exported the four relative-strength calculation functions from `src.domains.indicators`.
- No dedicated test module existed; current fallback/registry behavior is covered through broader workflows.
- Static AST parsing and stale-path checks passed. Tests were not run.

### Step 14 — split momentum-quality responsibilities

- Split the mixed `src/indicators/custom/momentum_quality.py` responsibilities: raw indicator generation moved to `src/domains/indicators/momentum_quality.py`, scoring rules to `src/domains/strategies/momentum_quality.py`, and their composition to `src/gates/momentum_quality.py`.
- Updated the implementation registry, research caller, strategy package exports, and backtest code-revision inputs.
- Renamed and moved the focused cross-domain test to `integration_tests/gates/test_momentum_quality.py`.
- AST parsing passed across 169 Python files and stale source-path checks passed. Tests were not run.
### Step 15 — platform-kernel contract tests

- Moved `tests/test_platform_kernel.py` to `tests/platform_kernel/test_platform_kernel.py` to mirror the `src/platform_kernel/` package.
- The four focused unit tests and their imports were unchanged; pytest discovers nested `tests/` packages through the configured test path.
- Tests were not run.

### Step 16 — platform-kernel artifact-store tests

- Moved `tests/test_sqlite_artifact_store.py` to `tests/platform_kernel/test_sqlite_artifact_store.py`; the test primarily verifies the platform kernel's SQLite artifact store.
- The file contents are unchanged. Its catalog/publisher setup remains in the same focused boundary test.
- Tests were not run.

### Step 17 — platform-kernel SQLite migration tests

- Moved `tests/test_sqlite_migrations.py` to `tests/platform_kernel/test_sqlite_migrations.py`; its cases cover namespaced schema migration behavior in `src/platform_kernel/sqlite.py`.
- The file contents and imports are unchanged.
- Tests were not run.

### Step 18 — portfolio-accounting projection test

- Moved `tests/test_portfolio_accounting.py` to `tests/portfolio_accounting/test_portfolio_accounting.py`, mirroring the current `src/portfolio_accounting/` package.
- Its single FIFO projection unit test and imports are unchanged.
- Tests were not run.

### Step 19 — portfolio-engine unit tests

- Moved `tests/test_portfolio_engine.py` to `tests/portfolio_engine/test_portfolio_engine.py`, mirroring the current `src/portfolio_engine/` package.
- Kept its 15 decision-engine tests together; two also use the backtesting runner to verify portfolio behavior across steps. Imports and test contents are unchanged.
- Tests were not run.

### Step 20 — split mixed jobs, ledger, and backtesting tests

- Replaced `tests/test_jobs_ledger_backtesting.py` with three focused unit-test modules: `tests/application/test_jobs.py`, `tests/domains/portfolio_accounting/test_ledger.py`, and `tests/backtesting/test_backtesting.py`.
- Preserved all four test functions and their names; each now imports only the APIs it exercises.
- Tests were not run.

### Step 21 — portfolio HTTP integration test

- Moved `tests/test_portfolio_web.py` to `integration_tests/gates/test_portfolio_web.py`; it exercises Flask routes together with the execution ledger and market repository.
- The ownership inventory assigns `application/portfolio_web.py` to the gates HTTP layer. Test contents and imports are unchanged.
- Tests were not run.

### Step 22 — split broker execution and HTTP integration tests

- Split `tests/test_broker_execution.py` into `integration_tests/gates/test_broker_execution.py` for six broker-service/gateway cases and `integration_tests/gates/test_broker_web.py` for the Flask route case.
- Preserved all seven test functions and names. Shared local fixtures are kept within each focused test module.
- Tests were not run.

### Step 23 — portfolio-engine ATR exit tests

- Moved `tests/test_atr_exit_rules.py` to `tests/portfolio_engine/test_atr_exit_rules.py`, matching its `src.portfolio_engine` dependency.
- The six focused tests and local fixtures were unchanged.
- Tests were not run.

### Step 24 — split phase-five portfolio tests by owner

- Split `tests/test_phase5_portfolio.py` into `integration_tests/execution/test_kite_accounts.py`, `tests/portfolio_accounting/test_opening_position_projection.py`, `integration_tests/portfolio_accounting/test_ledger_opening_positions.py`, and `integration_tests/gates/test_portfolio_sync.py`.
- Preserved all four test function names. Updated the strategy fixture path for its new nested location.
- Tests were not run.

### Step 25 — indicator DAG/cache regression tests

- Split `tests/test_phase1_dag_fixes.py` by source responsibility: graph identity coverage is in `tests/domains/indicators/test_dag.py`, and cache revision coverage is in `tests/domains/indicators/test_node_cache.py`.
- The recursive DAG hash and cache revision tests were unchanged.
- Tests were not run.

### Step 26 — architecture import-boundary test

- Moved `tests/test_import_boundaries.py` to `tests/architecture/test_import_boundaries.py`; it checks dependency rules across multiple domain packages.
- Updated its source-root calculation for the nested test location; the rule and assertions are unchanged.
- Tests were not run.

### Step 27 — application shell integration test

- Moved `tests/test_application_shell.py` to `integration_tests/test_application_shell.py`; it creates the full app through root-level `run.create_app()` and checks the shell's HTTP endpoints.
- Its single test and import remain unchanged.
- Tests were not run.

### Step 28 — cross-domain artifact-lineage integration tests

- Moved `tests/test_artifact_lineage.py` to `integration_tests/application/test_artifact_lineage.py`; its cases combine artifact storage, catalog invalidation, and market/reference snapshots.
- The three test functions, names, and imports remain unchanged.
- Tests were not run.

### Step 29 — corporate-actions workflow integration tests

- Moved `tests/test_corporate_actions.py` to `integration_tests/gates/test_corporate_actions.py`; its cases coordinate corporate-action processing with market persistence, publication, and accounting.
- Preserved all four test functions, names, and imports. Updated the Phase 3 file list.
- Tests were not run.

### Step 30 — durable jobs unit tests

- Moved `tests/test_durable_jobs.py` to `tests/gates/test_durable_jobs.py`, alongside the existing worker tests and matching the planned gate ownership of durable job infrastructure.
- Its two job-store/worker unit tests and imports are unchanged.
- Tests were not run.

### Step 31 — index-poller scheduling integration tests

- Moved `tests/test_index_poller.py` to `integration_tests/gates/test_index_poller.py`; it verifies persisted poller intent, durable job submission/reconciliation, and error recording across the planned market/gate seam.
- Preserved all three test functions, names, and imports.
- Tests were not run.

### Step 32 — split market-provider adapter tests by owner

- Split `tests/test_market_provider_adapters.py` into `tests/market_data/test_market_provider_adapters.py`, `tests/domains/execution/test_streaming_provider.py`, and `integration_tests/gates/test_market_jobs.py`.
- The market adapter module retains the original basename. All four test functions and names are preserved; provider fakes remain local to the module that uses them.
- Tests were not run.

### Step 33 — split Kite profile and authentication tests

- Split `tests/test_kite_profiles.py` into `tests/domains/execution/test_kite_profiles.py`, `integration_tests/gates/test_kite_profile_isolation.py`, and `integration_tests/gates/test_kite_auth_callback.py`.
- Preserved all three test functions and names; only the credential-selection case remains a unit test, while full-app and HTTP callback cases are integration tests.
- Tests were not run.

### Step 34 — market-data ingestion integration test

- Moved `tests/test_ingestion.py` to `integration_tests/market_data/test_ingestion.py`; it exercises ingestion across normalized market data, the artifact store, catalog, and publisher.
- Preserved its test function, name, imports, and assertions. Updated documentation references to the new path.
- Tests were not run.

### Step 35 — split live-quote persistence, provider, and stream tests

- Split `tests/test_live_quotes.py` into `tests/market_data/test_live_quotes.py` for quote validation/persistence and `integration_tests/gates/test_live_quote_stream.py` for stream lifecycle and HTTP behavior.
- Moved the provider timestamp case into the existing `tests/domains/execution/test_streaming_provider.py` module. Preserved all eight test functions and names.
- Tests were not run.

### Step 36 — indicator DAG operation tests

- Moved `tests/test_phase1_dag_operations.py` to `tests/domains/indicators/test_dag.py`, matching the DAG executor and registry APIs it covers.
- Preserved the parameterized approved-operation cases, manifest test, and imports. Updated documentation references to the new path.
- Tests were not run.

### Step 37 — indicator DAG output tests

- Moved `tests/test_phase1_dag_output.py` to `tests/domains/indicators/test_dag_output.py`, matching the DAG executor and registry APIs it verifies.
- Split `tests/test_phase1_acceptance.py` across application startup integration coverage, strategy-definition gate validation, indicator registry validation, and DAG graph identity coverage.
- Split `tests/test_phase4_strategy_cleanup.py` by strategy runtime, application composition, research persistence, and pipeline scheduling ownership; combined the exact retained-strategy and seed-idempotence assertions.
- Preserved the output-selection, cache-identity, and invalid-operation tests with their existing names and imports. Updated documentation references.
- Tests were not run.

### Step 38 — split Phase 1 progress and coverage tests

- Split `tests/test_phase1_progress_coverage.py` into `integration_tests/gates/test_session_coverage.py`, `tests/gates/test_job_progress.py`, `integration_tests/gates/test_market_jobs.py`, `integration_tests/gates/test_pipeline_preparation.py`, and `integration_tests/gates/test_operations_progress.py`.
- Preserved all twelve test functions and names; grouped shared fixtures with the cases they support.
- Tests were not run.

### Step 39 — split market coverage API, workflow, and repository tests

- Split `tests/test_market_coverage.py` into `integration_tests/gates/test_market_coverage.py`, `integration_tests/gates/test_market_refresh.py`, and `tests/market_data/test_fetch_coverage.py`.
- Preserved all six test functions and names; each module now covers either HTTP, refresh workflow, or market-repository coverage persistence.
- Tests were not run.

### Step 40 — reference-data liquidity-universe tests

- Moved `tests/test_liquidity_universe.py` to `tests/reference_data/test_liquidity_universe.py`, matching `src.reference_data` and its liquidity policy/snapshot builder.
- Preserved all four test functions and names, including the artifact serialization assertion. Updated documentation references.
- Tests were not run.

### Step 41 — liquidity-universe job integration test

- Moved `tests/test_liquidity_universe_job.py` to `integration_tests/gates/test_liquidity_universe_job.py`; the test submits and runs the composed job, then verifies its cataloged reference-data artifact.
- Preserved its helper, test function, name, and assertions. Updated documentation references.
- Tests were not run.

### Step 42 — publication recovery integration test

- Moved `tests/test_publication_recovery.py` to `integration_tests/application/test_publication_recovery.py`; it verifies recovery across the artifact store, catalog, and publisher.
- Preserved its single test function, name, and assertions. Updated documentation references.

### Step 43 — shared redaction helpers

- Moved structured-value, error, and text redaction helpers from `src/application/security.py` to `src/platform_kernel/security.py`.
- Moved the logging filter to `src/gates/security.py`; log-handler setup remains at the application entry point.
- Updated runtime callers and tests to use the owning module. `src/application/security.py` was a compatibility facade at this checkpoint; it was removed when `src/application` was retired in Step 92.
- Focused redaction, regression, and recursive architecture tests passed (37 tests). Full-suite verification was pending at this migration checkpoint; see the later Steps 84–94 evidence and current final-validation status.

### Step 44 — operations CLI entry point

- Moved the existing `screener-ops` command implementation to `src/gates/cli.py` and changed the package script to `src.gates.cli:main`.
- At this checkpoint, the old `src.application.cli:main` path was temporarily preserved while CLI tests moved to the gate entry point; the facade was subsequently removed in Step 92.
- At this migration checkpoint, CLI imports were being moved into gates; Steps 72–94 later retired the application package and its transition entries.
- Existing CLI tests and the recursive import-boundary checks passed after the move.

### Step 45 — recursive dependency checks and migration manifest

- Replaced the top-level-only import scan with recursive AST checks over target domains, `platform_kernel`, and gates, including relative and `TYPE_CHECKING` imports plus dynamic-import auditing.
- Added file/import-specific transitional exceptions with reasons and a test that fails on stale allowlist entries.
- Added `docs/architecture/restructure-migration-manifest.md` with current source ownership, compatibility routes/jobs/CLI/schema namespaces, moved test paths, and baseline evidence.
- Regenerated `docs/src-file-inventory.md` from the current AST while preserving its existing ownership and hotspot review.
- Tests were not run.

### Step 46 — gates entry points and HTTP adapters

- Moved application composition and runtime configuration to `src/gates/composition.py` and `src/gates/runtime.py`.
- Moved the Flask factory and Waitress/background lifecycle to `src/gates/app.py`; root `run.py` now re-exports `configure_logging`, `create_app`, and `main` as the stable launcher.
- Moved the dashboard, wiki, operations, and resource API blueprints to `src/gates/http/`; updated source, test, integration-test, and tool imports. Adjusted template/wiki roots to preserve repository asset resolution.
- Updated `screener-ops` to `src.gates.cli:main`. Existing application route/composition/runtime import references were removed in this batch.
- Static syntax parsing and source import searches passed. Tests were not run.

### Step 47 — consolidate pure domain packages

- Moved `market_data`, `reference_data`, `portfolio_engine`, and `portfolio_accounting` into `src/domains/` and updated callers across source, tools, and tests.
- Merged the existing `PortfolioPerformance` service into the consolidated accounting package exports.
- Superseded by Step 78: backtesting now receives a portfolio-engine port and the implementation lives under `src/domains/backtesting`; the gate adapter supplies concrete engine types.
- Regenerated `docs/src-file-inventory.md` from the current 104 source modules. Full-suite verification was pending at this migration checkpoint; later verification status is recorded in the migration manifest.

### Step 48 — operations domain

- Moved durable job records, event cursors, leases, and local worker execution to `src/domains/operations/`.
- Added curated package exports; updated in-repository callers to import jobs and workers from that public API.
- Retained `src/application/jobs.py` and `worker.py` as narrow compatibility facades pending the external-caller audit.
- Moved the job store and worker unit tests to `tests/domains/operations/` and removed now-obsolete gate-to-application allowlist entries.
- AST parsing reports 107 source modules with no syntax errors. Tests were not run.

### Step 49 — artifacts domain

- Moved SQLite artifact catalog and recoverable publication implementations to `src/domains/artifacts/`.
- Updated gates, workflows, tests, and tools to use the curated artifact package API. Kept narrow application re-export facades for external compatibility.
- Removed four now-obsolete gate-to-application transition entries; table namespace and artifact payload behavior are unchanged by the move.
- Tests were not run after the relocation.

### Step 50 — strategy contracts and positional signals

- Moved strategy revision/snapshot contracts into `src/domains/strategies/api.py`; `src/strategies` now provides compatibility exports.
- Moved positional-trend feature and signal calculations into `src/domains/strategies/positional_trend.py` and updated source, tests, and tools.
- Moved cross-domain custom implementation registration into `src/gates/indicator_implementations.py`; gates now wire indicator and strategy calculations through their public packages.
- Updated source-hash paths and removed the obsolete gate import exception for `src.indicators.custom`.
- AST parsing covers 113 source modules with no syntax errors; all 48 declared transition entries match observed imports. Tests were not run.

### Step 51 — calendar and NSE provider ownership

- Moved the observed-session `TradingCalendar` to `src/domains/market_data/calendar.py` and exported it from market data's public package.
- Moved the NSE constituent/corporate-action HTTP client and URL constants to `src/domains/reference_data/nse_provider.py` and exported the supported adapter.
- Updated application workflows and the portfolio HTTP gate to use the domain packages; removed the resolved calendar exception.
- AST analysis covered 115 Python files including `run.py`, with zero syntax errors, zero direct cross-domain imports, and 47 exact transitional imports all observed. Tests were not run.

### Step 52 — positional-trend gate workflow

- Moved `PositionalTrendJobs` into `src/gates/workflows/positional_trend.py`, where it sequences market membership, strategy-owned signals, strategy runtime, and artifact publication.
- Updated composition, the HTTP adapter, and tests to the new workflow location; kept the former application module as a one-class compatibility facade.
- Removed its two resolved gate-to-application exceptions. Static parsing covered 117 files including `run.py`, with zero syntax errors and 45 of 45 transitional imports observed. Tests were not run.

### Step 52 — expose calculation APIs to gate workflows

- Exported the approved indicator calculations through `src.domains.indicators.api` and strategy signal/ranking calculations through `src.domains.strategies.api`.
- Updated the gate implementation registry and positional-trend workflow to import only those public API modules; the architecture test previously found direct imports of private indicator/strategy modules.
- Corrected a malformed import placement in the newly added positional-trend workflow discovered by the recursive AST parser.
- Recursive architecture tests passed (4 tests), positional-trend contract/integration tests passed (17 tests), and the final full unit/integration suite passed (453 tests).

### Step 53 — market repository ownership and quote extraction

- Moved `MarketRepository` and `TrackedInstrument` into the market-data domain and updated callers to its public API; the old application module now forwards imports.
- Extracted current/historical index quote operations into `src/domains/market_data/index_quotes.py` while preserving the `MarketRepository` surface and legacy schema migration sequence.
- Removed five gate-to-application repository exceptions. Static AST analysis covered 119 files, including `run.py`, found zero syntax errors or direct cross-domain imports, and matched all 40 remaining transition entries. Tests were not run.
- The main repository still aggregates instruments, universes, market history, indicators, and corporate-action state. Split these stores by owning domain before Phase 3 is complete.

### Step 54 — instrument and universe repository extraction

- Moved `TrackedInstrument` and identity/token/universe/exit-eligibility persistence methods into `src/domains/market_data/universe_repository.py`.
- Composed the new repository concern and index quote concern into `MarketRepository`, preserving its callable surface and central historical migration setup.
- AST audit covers 120 files including `run.py`, with zero syntax errors or direct cross-domain imports and all 40 declared transition entries observed. Tests were not run.

### Step 55 — market history repository extraction

- Moved market bars, sessions, revisions, quality events, indicators, and fetch coverage into `src/domains/market_data/history_repository.py`.
- Moved token assignment/history read methods to the existing universe repository concern.
- `MarketRepository` composes history, universe, and index-quote concerns without changing its constructor, public method surface, or the historical `market` schema migration.
- AST audit covers 123 Python files including `run.py`, with zero syntax errors or direct cross-domain imports and all 40 declared transition entries observed. The current source inventory contains 122 modules under `src/`. Tests have not been rerun since the repository extractions.

### Step 53 — strategy definition persistence ownership

- Moved YAML normalization, strategy validation, and the SQLite strategy definition/revision repository to `src/domains/strategies/definitions.py`.
- Replaced direct indicator/gate imports in the strategies domain with an injected `StrategyDefinitionValidator` contract.
- Added `src/gates/strategy_validation.py` to adapt the indicator API and custom implementation registry; kept `src/gates/strategy_definitions.py` as a compatibility composition facade.
- Focused strategy-definition, Strategy 4, account and architecture tests passed (16). The full unit/integration suite passed (453 tests in 102.41s). Ruff checks passed for the moved domain and adapter files.

### Step 56 — reference-data repository ownership and gate composition

- Moved instrument identity, token observation, reference snapshot, and token lookup persistence to `src/domains/reference_data/repository.py`.
- Moved active-universe membership, exit-eligibility, corporate-action event state, and its watermark out of the market-data repository into the reference-data repository; removed the market-data compatibility mixin.
- Kept the market-session/reference-eligibility join and atomic corporate-event/market-bar adjustments in `src/gates/repositories.py`, which composes the public market and reference repositories while preserving the existing aggregate API. Legacy `market` SQLite migrations remain in their existing versioned sequence.
- AST and import-boundary checks pass (124 Python files parsed, zero syntax errors, zero cross-domain imports, zero boundary violations, all 40 transitions current). Smoke checks covered reference instruments, active-universe membership, market bars, corporate events, transitions, and watermarks. No pytest run after this change.

### Step 57 — owner schema and market/reference gate seams

- Added `src/domains/reference_data/schema.py` with a namespaced owner migration for reference identities, tokens, universes, and corporate-action records. `ReferenceDataRepository` can now initialize those tables independently. The historical `market` migration remains for compatibility; its series-column step is idempotent so either initialization order works.
- Moved composite coverage/history/session readers and `TradingCalendar` into gates; market-history writes receive equity/index classification from the gate, and quality-event validation relies on the table foreign key while preserving its domain error.
- Moved the atomic corporate-action / market-bar operations into the gate repository aggregate. Market-data runtime repositories no longer query reference-owned tables.
- Static AST and recursive boundary audits pass (125 files including `run.py`, zero syntax errors/violations, all 40 tracked transitions current). Smoke checks covered both migration initialization orders, composite reads, calendar sessions, quality validation, and corporate-action adjustment. Pytest was not run after this change. Owner migration and duplicate DDL separation for market data remain.
- Added `tests/reference_data/test_repository_migrations.py` for independent reference initialization and reference-first/legacy-market upgrade order. Ruff and AST parsing pass; pytest has not been run.

### Step 58 — market-data owner schema migration

- Added `src/domains/market_data/schema.py` with its own `market_data` namespace/version 1 for bars, index quotes/history, indicators, market-history revisions, quality events, and fetch coverage.
- Fresh repositories now initialize through `reference_data` and `market_data` owner migrations only; they do not create the legacy `market` namespace. When that legacy namespace exists, `MarketRepository` completes its historical migrations before applying owner migrations idempotently.
- Moved the old 17-version mixed mapping into `src/domains/market_data/legacy_schema.py` as the existing-database bridge. Added market-owner and legacy-upgrade regression tests; the legacy fixture upgrades from v10 and asserts retained reference rows plus final migration versions.
- Manual smoke verification passed for fresh owner-only initialization and legacy v10 upgrade to v17 followed by both owners. AST parsing covers 129 Python files including `run.py` and both migration tests. Recursive import-boundary checks found zero violations and all 40 transitions current; focused Ruff passes. Pytest was not run. Removing duplicate DDL from the bridge after the upgrade window remains outstanding.

### Step 59 — corporate-action gate workflow

- Moved the cross-domain `CorporateActions` implementation from `src/application/corporate_actions.py` to `src/gates/workflows/corporate_actions.py`; the old module now re-exports the class and threshold constant as a compatibility facade.
- Updated composition, market HTTP, and backtest coordination to use the gate workflow. Moved its behavioral tests to `tests/gates` and updated integration tests. Removed the two gate-to-application exceptions. The workflow consumes a narrow ledger protocol and does not import the execution package.
- Recursive architecture audit reports zero violations and matches all 38 declared transitional imports. Focused Ruff passes on the workflow, facade, callers, and tests. Pytest was not run.

### Step 60 — liquidity-universe gate workflow

- Moved the liquidity job's payload validation, reference-domain model construction, and artifact publication from `src/application/liquidity.py` to `src/gates/workflows/liquidity_universe.py`. `src/domains/reference_data` retains the standalone liquidity policy and snapshot calculation; the old application module is a compatibility facade.
- Updated composition to import the gate workflow and removed its exact application transition. The existing integration job contract remains under `integration_tests/gates`.
- Recursive architecture audit reports zero violations and matches all 37 declared transitions. Focused Ruff and AST checks pass; pytest was not run.

### Step 61 — retire unused application compatibility shims

- Removed four compatibility-only application files after a recursive production, test, integration, and tool caller audit found no imports: corporate actions, exchange calendar, NSE client, and positional-trend jobs.
- Their implementations remain at `src/gates/workflows/corporate_actions.py`, `src/gates/workflows/trading_calendar.py`, `src/domains/reference_data/nse_provider.py`, and `src/gates/workflows/positional_trend.py`, respectively. The migration manifest records each removed path and its owner.

### Step 62 — universe snapshot gate workflow

- Moved `UniverseJobs` and its focused unit test to the gates workflow/test trees. Composition and behavioral fixtures now import the gate path; the old application module was removed after auditing all source, test, integration, and tool callers.
- Provider, domain contracts, and reference persistence remain in `src/domains/reference_data`; coordination with market-session evidence and exit eligibility is owned by `src/gates/workflows/universe.py`.
- Focused Ruff passes. Pytest was not run.

### Step 63 — portfolio sync gate workflow

- Moved account-scoped setup and reconciliation into `src/gates/workflows/portfolio_sync.py`, with execution/accounting access expressed as injected protocols. Updated composition, integration, and audit-tool imports and removed the old application file.
- Published retained strategy IDs through `src/domains/strategies/api.py`; both application strategy runtime and execution account linking now consume that contract.
- Focused Ruff passes. Pytest was not run.

### Step 64 — market refresh gate workflow

- Moved the bounded refresh and reconciliation planner to `src/gates/workflows/market_refresh.py`; updated composition, market HTTP, integration, and behavioral imports and removed the application source after a caller audit.
- Scheduling and held-position coordination remain in gates; market coverage and session reads remain behind their owning domain/gate interfaces.
- Recursive boundary audit reports zero violations with all 33 transitions observed; AST, exact inventory coverage, and focused Ruff pass. Pytest was not run.

### Step 65 — pipeline preparation workflow and market index contract

- Moved manual prerequisite sequencing to `src/gates/workflows/pipeline_preparation.py`, updated composition and integration imports, and retired the old application module after caller audit.
- Centralized the stable NSE index symbol set in `src/domains/market_data` and kept the prior phase-named constant as an application compatibility alias.
- Recursive boundary audit reports zero violations with all 32 transitions observed; AST, exact inventory coverage, focused Ruff, and gate workflow import smoke pass. Pytest was not run.

### Step 66 — index-poller gate lifecycle

- Moved durable index-quote scheduling, lease state, and background lifecycle into `src/gates/workflows/index_poller.py`; updated app startup, CLI, HTTP, composition, and integration imports and removed the application implementation.
- Preserved the existing `index_poller` schema namespace and version sequence while recording gate ownership of that scheduler state.
- Recursive boundary audit reports zero violations with all 28 transitions observed; AST, exact inventory coverage, focused Ruff, and workflow import smoke pass. Pytest was not run.

### Step 67 — intraday stream gate lifecycle

- Moved the durable intraday stream lease into `src/gates/workflows/intraday_stream.py`; updated CLI, composition, HTTP, and regression/integration imports and removed the application implementation.
- Preserved the `intraday_stream` migration namespace and schema versions while assigning lifecycle state and control to gates.
- Recursive boundary audit reports zero violations with all 25 transitions observed; AST, exact inventory coverage, focused Ruff, and workflow import smoke pass. Pytest was not run.

### Step 68 — live quote, stop alert, and stream ownership

- Moved account-scoped live quote validation, persistence, and freshness decisions into `src/domains/market_data/live_quotes.py`; retained the `live_quotes` schema namespace/version and exposed `LiveQuotes` through the market-data API.
- Moved durable fill-free ATR stop evaluation and alert persistence into `src/domains/portfolio_accounting/intraday_alerts.py`. The domain consumes narrow ledger, risk-projection, and alert-publication ports rather than importing execution/artifact implementations.
- Moved the live stream controller to `src/gates/workflows/live_quote_stream.py`; routes and composition use market-data, portfolio-accounting, and gate APIs. The Kite streaming adapter remains in the mixed application provider module for a separately reviewed provider migration.
- Split alert verification into `tests/portfolio_accounting/test_intraday_alerts.py` and `integration_tests/gates/test_intraday_alerts.py`; the stream lease HTTP lifecycle regression now lives with stream gate integration tests. Removed the two unused application shims after a caller audit.
- Refreshed the current AST inventory and exact transition allowlist. Recursive boundary checks report zero violations and observe all 23 declared transitions; AST parsing covers 224 source, test, integration, tool, and entry files. Focused Ruff and composition/workflow import smoke checks pass. Pytest was not run.

### Step 69 — market provider adapter ownership

- Moved rate-limited historical-bar, instrument-list, and quote adapters to `src/domains/market_data/providers.py` and exported them through the public market-data API. They retain injected clients, validation, throttling, and normalization behavior.
- Updated market jobs and adapter/throttle callers to use the domain owner. `src/domains/market_data/providers.py` owns historical/instrument/quote adapters; the account-scoped stream provider moved to `src/domains/execution/streaming_provider.py` in Step 87.
- Updated the source inventory and provider ownership plan. Pytest was not run; verification is recorded in the restructure migration manifest.

### Step 70 — market job and ingestion workflows

- Moved `KiteMarketJobs` to `src/gates/workflows/market_jobs.py`; composition registers its methods directly as durable handlers. Provider reads, repository writes, coverage, artifact publication, and alert polling are coordinated at the gate boundary.
- Moved `ingest_market_bars` to `src/gates/workflows/market_ingestion.py` and relocated its integration test under `integration_tests/gates`.
- Updated all production and test callers, removed the two application implementations, and retired the exact composition-to-application transition. Composition binding and raw-to-normalized lineage smoke checks pass; zero boundary violations remain with 22 transitions. Pytest was not run.

### Step 71 — retire unused artifact facades

- Removed the five-line `src/application/catalog.py` and `src/application/publication.py` wrappers after recursive source, test, integration, tool, and entry-point searches found no remaining imports.
- Callers already use the public `src.domains.artifacts` API; schema ownership and publication behavior are unchanged. The current source inventory and manifest reflect the removed paths.


### Step 72 — execution authentication ownership

- Moved Kite authentication and credential handling into `src/domains/execution`; app, CLI, composition, HTTP, and execution adapters consume the curated domain API.
- The service preserves the existing profile isolation and atomic token replacement. The broker adapter remains under `src/execution_gateway` for a later cohesive execution-gateway migration.

### Step 73 — remove unused application re-exports

- Removed five unused module-level wrappers after confirming no production, test, integration, tool, or entry-point callers. The operations, security, strategy, and CLI capabilities remain in their canonical owners.
- Package-level operations exports and the stable `run.py` entry point remain available.

### Step 74 — remove market repository re-export

- Removed the unused application wrapper. Cross-domain composite reads remain gate-owned; domain table owners remain under their own repositories. The retired path is still asserted by the boundary regression.

### Step 75 — portfolio proposal persistence ownership

- Added the portfolio-engine-owned `PortfolioProposalStore` for the existing `actions` schema. `ActionJobs` delegates proposal reads, writes, recovery projection, event writes, and pending decisions to it.
- The processing path injects the caller-owned SQLite transaction into the store so ledger-version validation and proposal status/event changes retain their prior transaction boundary. Remaining cross-domain orchestration is still in the legacy coordinator.

### Step 76 — move portfolio action coordination to gates

- Moved the cross-domain ActionJobs coordinator into `gates/workflows/portfolio_actions.py` after proposal persistence became a portfolio-engine capability. Updated composition, routes, and integration/regression callers.
- Strategy ID alias rules and signal helper exports are now discoverable through `domains/strategies`; the remaining legacy strategy runtime retains compatibility exports.

### Step 77 — backtest run persistence ownership

- Moved versioned `backtest_runs` schema and its index operations into `domains/backtesting`. Application orchestration now delegates run insert, list, artifact lookup, and delete to `BacktestRunStore`.
- Kept normal duplicate rejection and Strategy 4 insert-if-missing behavior distinct. Remaining replay coordination and calculations are not yet moved.

### Step 77 — backtest run persistence ownership

- Added `domains/backtesting.BacktestRunStore` for the existing version-1 table and index operations; `BacktestJobs` delegates run persistence/query operations to that owner.
- Replay coordination moved to `src/gates/workflows/backtesting.py` in Step 79; domain-owned persistence and simulation are described in later entries.

### Step 78 — consolidate backtesting engine under its domain

- Moved the replay/result module into `domains/backtesting/simulation.py`, composed it with the public domain API and run store, and deleted the old package after moving all internal imports.

### Step 78 — invert replay’s portfolio dependency

- The backtesting domain now defines a neutral `PortfolioEnginePort` and owns its execution-assumptions DTO. `gates/backtesting_adapter.py` supplies portfolio-engine evaluation and translates those values. No backtesting-domain module imports portfolio-engine code.
- Replay regressions inject the same adapter at the edge.


### Step 79 — move backtesting workflow coordination to gates

- Moved the replay job coordinator to `gates/workflows/backtesting.py`; its persistence and simulation dependencies are now backtesting-domain APIs, with market history identities read through the market-data owner.
- The remaining research service and Strategy 4 input-loader imports are recorded as exact transitional seams.


### Step 80 — Strategy 4 simulation and input ownership

- Strategy 4 policy and next-open replay now live in the strategies domain; the mixed CSV/SQLite loader module was split into a gate-owned composite input adapter and the strategies implementation.
- Production backtest and CLI callers use the new domain/gate paths. The adapter’s direct cross-owner SQL remains a future move to market/reference repository contracts.


### Step 81 — move StrategyRuntime composition to gates

- The strategy runtime now resides under `src/gates`, where it coordinates public strategy and indicator contracts with gate-owned implementation adapters. Canonical identity rules remain in the strategies domain.
- Composition and research/pipeline consumers use the new gate path; the exact composition transition to the legacy application module is retired.


### Step 82 — research schema and persistence ownership

- Research table migrations and SQL access now live in `src/domains/research/repository.py`. `ResearchJobs` delegates score/ranking projections, percentile cache, and lineage persistence while retaining workflow/API behavior.
- The `research` namespace and migration sequence are unchanged. At this migration checkpoint, the application class still mixed research calculations, artifact reads/publication, and job orchestration; these responsibilities were later split into research-owned modules and `gates/workflows/research.py`.

### Step 83 — research calculations

- Pure sector scoring, correlation/clustering, anomaly statistics, and weekly score aggregation are owned by `domains/research/calculations.py` and re-exported by `domains/research`.
- `ResearchJobs` coordinates market history, strategy runtime, artifact publication, research repository projections, and durable job work in `gates/workflows/research.py`.


### Step 84 — move research orchestration into gates

- `ResearchJobs` now lives in `gates/workflows/research.py`, with range-command parsing in `gates/payloads.py`. Composition, HTTP, backtesting, portfolio actions, and tests use the gate-owned workflow.
- The workflow calls public APIs for research, indicators, and strategies; calculations and research persistence remain in the research domain. The composition’s strategy seed path and indicator implementation hash path were adjusted for the new module depth.


### Step 85 — research pipeline persistence and coordination

- The research domain owns the unchanged `research_pipeline` schema namespace, migrations, pipeline identity records, and stage-job pointers. The gates workflow owns date validation, trading-session resolution, child-job orchestration, deferred advancement, retries, cancellation, and status aggregation.


### `src/domains/portfolio_engine/risk_reservations.py` — 78 lines

**Imports**
- L3: `from __future__ import annotations`
- L5: `import sqlite3`
- L6: `from pathlib import Path`
- L8: `from src.platform_kernel.sqlite import migrate_sqlite`

**Module-level symbols**
- class `RiskReservationRepository` (L11): __init__ L14, active_for_account L32, upsert L42, release L70


### Step 86 — portfolio risk orchestration and reservation ownership

- `portfolio_engine` owns the unchanged risk-reservation schema and row persistence; `gates/workflows/managed_risk.py` owns the cross-domain risk check. The repository executes against the guard’s active SQLite connection so ledger, limits, and reservations stay in one transaction.

- Step 87 moved the account-scoped Kite stream adapter into execution, exposed it through the execution API, and removed the unreferenced run-publication and liquidity application facades after a full caller audit. Steps 88–90 moved portfolio risk configuration, broker accounts, and the broker provider adapter to their owners. Step 91 moved the ledger implementation to portfolio accounting while preserving the package-level compatibility export; that compatibility package was retired in Step 94. Step 92 removed the empty application package after a caller audit. Step 93 removed the unused top-level indicators and strategies facades after caller audits. Step 94 moved broker persistence to execution, orchestration to gates, and removed the final legacy execution package.
- Step 88 moved risk-limit validation and persistence into `portfolio_engine`, preserving its migration namespace/version and retiring the old execution-gateway risk-guard module. Step 89 moved Kite account/session persistence into execution while injecting the supported strategy-ID contract from composition.
