# Domain and gates restructure migration manifest

> **Clean-break update (2026-10-03):** This document contains historical snapshots and decisions from intermediate implementation steps. They are not compatibility requirements. Do not preserve earlier strategy IDs, routes, job aliases, database migration histories, existing rows, or artifact IDs. Current source schemas initialize from an empty database at version 1; existing development databases may be discarded.

Prepared from the current worktree on 2026-10-03. This is a live tracker for `docs/architecture/domain-gates-restructure-plan.md`; it does not authorize behavior changes. Existing worktree edits were present before this continuation and are preserved.

## Baseline and evidence

- Branch at inspection: `feature/codex_enhancement`, 7 commits ahead of `origin/feature/codex_enhancement`; the worktree had extensive pre-existing edits and moves. Do not reset or clean it as part of this migration.
- `docs/src-file-inventory.md` records current source imports and declared symbols; `docs/architecture/domain-module-inventory.md` records prior ownership review and migration log. This manifest cross-references those inventories instead of duplicating symbol lists.
- Project configuration requires Python `>=3.13`; system Python is 3.13.7 without pytest. Workspace `.venv` has Python 3.12.14 and pytest 9.1.1. Poetry currently selects Python 3.12 and refuses to run because it does not meet the project constraint.
- **Historical note:** earlier steps used both `tests/` and `integration_tests/`. The current test tree is consolidated under `tests/`; discovery and `make test` use that root alone, and tests mirror source directories and basenames one-to-one.
- Initial full-suite attempt could not collect duplicate nested module names. Pytest `importlib` mode resolved those collisions; discovery now targets only `tests/`.
- Baseline with `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-restructure-baseline`: **427 passed, 1 failed, 4 errors**. Failure was the old non-recursive architecture assertion. Four test setup errors came from missing parametrization decorators in moved tests; their exact decorators are restored from committed originals. After restoring those decorators and replacing the stale architecture check, the full suite passed: **452 passed in 29.54s**. After the security-helper relocation and dynamic-import rules, the full suite passed: **453 passed in 31.16s**.
- The host temp root and `.pytest_cache` are access-denied, so use a fresh basetemp inside the workspace and disable the pytest cache plugin when running tests.
- Repository checks under the installed Python 3.12 virtualenv (the project requires Python 3.13+) found pre-existing formatting/lint/type/security debt: Ruff reported formatting differences and 68 lint findings (63 auto-fixable); mypy reported 162 errors in 33 files; Bandit reported 11 findings (10 medium, 1 low). These are baseline-wide results, not attributed to this restructure. The changed-file Ruff set is clean after this work segment.

## Compatibility surface inventory

- Imports and module-level public symbols: each current source entry in `docs/src-file-inventory.md`; legacy/moved symbols are also indexed in `docs/architecture/domain-module-inventory.md`.
- HTTP compatibility: blueprint names, route decorators, request/response shapes and registration order remain in their current `src/gates/http/` modules and `run.py`; each HTTP row below retains its blueprint module and is verified by matching integration test when present.
- Durable job types and CLI commands are registered by `src/gates/composition.py`, domain-owned operations job/worker APIs, and `src/gates/cli.py`; preserve names/payloads while mapping them to operations and gate handler adapters.
- SQLite table/schema namespace ownership and migration versions are currently declared by the repository/service constructors listed in the source inventory. Keep `instance/stock_screener.db`, table names, data formats, transaction boundaries and migration versions stable; the market repository method/table audit remains open.
- Path-sensitive resources include root `templates/`, `static/`, `strategies/`, `docs/wiki/`, `instance/`, `data/`, and source-hash inputs in pipeline/research/backtest modules. Centralize runtime resource roots before package-resource moves; no runtime data or secrets are to be moved or cleaned by this plan.

## Runtime compatibility map

These names and public shapes are current source contracts. Preserve them while moving implementations; update this snapshot when later phases intentionally change a contract.

### HTTP blueprints and route paths

- `actions` (`/api/actions`), [src/gates/http/actions.py]: `GET /execution-policy-parity/<artifact_id>`, `GET /proposals`, `GET /proposals/<proposal_id>`, `GET /proposals/<proposal_id>/events`, `GET /proposals/dates`, `GET /risk`, `POST /execution-policy-parity`, `POST /manual`, `POST /midweek-stop`, `POST /proposals/<proposal_id>/amend`, `POST /proposals/<proposal_id>/approve`, `POST /proposals/<proposal_id>/process`, `POST /proposals/<proposal_id>/reject`, `POST /proposals/bulk-decision`, `POST /risk/update`.
- `backtests` (`/api/backtests`), [src/gates/http/backtest.py]: `GET /runs`, `GET /runs/<run_id>`, `GET /runs/<run_id>/attribution`, `GET /walk-forward/<walk_forward_id>`.
- `broker` (`/api/portfolio`), [src/gates/http/broker.py]: `GET /baskets/<basket_id>`, `GET /execution-controls`, `GET /orders/<order_id>`, `POST /baskets`, `POST /baskets/<basket_id>/submit`, `POST /orders`, `POST /orders/<order_id>/manual-fill`, `POST /orders/<order_id>/reconcile`, `POST /orders/<order_id>/submit`, `POST /proposals/<proposal_id>/broker-intents`.
- `dashboard` (`/`), [src/gates/http/dashboard.py]: `GET /`, `GET /actions`, `GET /app`, `GET /backtest`, `GET /logs`, `GET /pipeline`, `GET /portfolio`, `GET /rankings`, `GET /settings`, `GET /universe`.
- `indicators` (`/api/indicators`), [src/gates/http/indicators.py]: `GET /catalog`, `GET /catalog/pandas_ta/<indicator_key>`.
- `kite_accounts` (`/api/broker-accounts`), [src/gates/http/kite_accounts.py]: `GET `, `GET /<broker_account_id>/holdings`, `GET /<broker_account_id>/login-url`, `POST `, `POST /<broker_account_id>/authenticate`, `POST /<broker_account_id>/validate`, `POST /reconcile`, `POST /setup`.
- `kite_auth` (`/`), [src/gates/http/kite_auth.py]: `GET /`, `GET /integrations/kite`, `GET /integrations/kite/<profile>/callback`, `GET /integrations/kite/callback`, `GET /integrations/kite/portfolio`, `POST /api/integrations/kite/<profile>/authorize`, `POST /api/integrations/kite/authorize`.
- `market` (`/api/market`), [src/gates/http/market.py]: `GET /bars/<symbol>`, `GET /bars/<symbol>/adjusted`, `GET /coverage`, `GET /indices/history`, `GET /indices/poller`, `GET /indices/quotes`, `GET /intraday/quotes`, `GET /intraday/stop-alerts`, `GET /intraday/stop-alerts/stream`, `GET /intraday/stream`, `GET /quality-events`, `POST /corporate-actions`, `POST /corporate-actions/liquidation-plan`, `POST /indices/poller`, `POST /intraday/live-stream`, `POST /intraday/stop-alerts`, `POST /intraday/stream`, `POST /reconcile`, `POST /refresh`.
- `operations` (`/api/operations`), [src/gates/http/operations.py]: `GET /jobs/<int:job_id>`, `GET /jobs/<int:job_id>/events`, `GET /worker/status`, `POST /jobs`, `POST /jobs/<int:job_id>/cancel`, `POST /worker/start`, `POST /worker/stop`, `POST /worker/work-once`.
- `pipelines` (`/api/pipelines`), [src/gates/http/pipeline.py]: `GET /research/<pipeline_id>`, `POST /research`, `POST /research/<pipeline_id>/cancel`, `POST /research/<pipeline_id>/stages/<path:stage_name>/retry`.
- `portfolio` (`/api/portfolio`), [src/gates/http/portfolio.py]: `GET /accounts`, `GET /accounts/<account_id>`, `GET /accounts/<account_id>/events`, `GET /accounts/<account_id>/journal`, `GET /accounts/<account_id>/summary`, `GET /accounts/<account_id>/ticker`, `GET /accounts/<account_id>/ticker/stream`, `GET /accounts/<account_id>/valuation`, `GET /accounts/<account_id>/valuation/history`, `GET /accounts/<account_id>/valuation/snapshots`, `GET /risk-config`, `POST /accounts`, `POST /accounts/<account_id>/cash-transfers`, `POST /accounts/<account_id>/fills`, `PUT /risk-config`.
- `positional_trend` (`/api/positional-trend`), [src/gates/http/positional_trend.py]: `GET /signals`, `POST /signals/build`.
- `reference` (`/api/reference`), [src/gates/http/reference.py]: `GET /fundamentals/<artifact_id>`, `GET /instruments`, `GET /instruments/<instrument_id>/token-history`, `GET /liquidity-universes/<artifact_id>`, `GET /macro-indicators/<artifact_id>`, `GET /market-capitalization/<artifact_id>`, `GET /tokens/<provider_token>`, `POST /fundamentals`, `POST /macro-indicators`, `POST /market-capitalization`, `POST /sectors`.
- `research` (`/api/research`), [src/gates/http/research.py]: `GET /<kind>`, `GET /<kind>/<artifact_id>`, `GET /anomalies/<artifact_id>`, `GET /ranking-weeks`, `GET /rankings`, `POST /anomalies`, `POST /correlations`, `POST /recalculate`, `POST /sector-rankings`.
- `strategies` (`/api/strategies`), [src/gates/http/strategies.py]: `GET /<strategy_id>/revisions`, `GET /active`, `GET /revisions/<revision_id>`, `POST /revisions`, `POST /revisions/<revision_id>/activate`.
- `universe` (`/api/universe`), [src/gates/http/universe.py]: `GET /diff`, `GET /members`, `GET /snapshots`, `POST /refresh`.
- `wiki` (`/`), [src/gates/http/wiki.py]: `GET /api/wiki/pages`, `GET /api/wiki/pages/<slug>`, `GET /wiki`.

The Flask app defines the direct health endpoints `GET /health/live`, `GET /health/ready`.

### Durable job handler types

The current `JobWorker` handler registry declares: `actions.generate-portfolio-proposal`, `artifacts.recover`, `backtest.attribute`, `backtest.run`, `backtest.stress`, `backtest.walk-forward`, `market.fetch-bulk-kite-bars`, `market.fetch-intraday-stop-alerts`, `market.fetch-kite-bars`, `market.fetch-kite-index-quotes`, `market.schedule-all-symbol-refresh`, `reference.detect-corporate-actions`, `reference.download-nifty500-constituents`, `reference.process-corporate-actions`, `reference.reconcile-market`, `reference.sync-snapshot-instruments`, `research.build-liquidity-universe`, `research.pipeline-advance`, `research.pipeline-prepare`, `research.positional-trend-build-range`, `research.positional-trend-build-signals`, `research.rebuild-indicators`, `research.rebuild-range`, `system.echo`, `universe.detect-exits`.

### CLI commands and package scripts

CLI commands: `backup-sqlite`, `check-sqlite`, `pipeline-status`, `poller-state`, `restore-sqlite`, `stream-state`, `work-once`.
Package scripts: `screener = run:main`, `screener-ops = src.gates.cli:main`.
`screener = run:main` remains the stable public application entry.

### SQLite migration namespaces and current table sets

All schemas remain in `instance/stock_screener.db`. Each owner initializes its complete current schema as version 1. There is no legacy market namespace, upgrade bridge, numbered strategy identifier mapping, or data-compatibility contract.

| Namespace | Current declaration | Versions | Current tables | Target owner |
|---|---|---|---|---|
| `actions` | `src/domains/portfolio_engine/proposal_store.py` | 1 | action_proposal_events, action_proposals | portfolio_engine |
| `backtest` | `src/domains/backtesting/repository.py` | 1 | backtest_runs | backtesting |
| `index_poller` | `src/gates/workflows/index_poller.py` | 1,2 | index_poller_leases | gates |
| `intraday_alerts` | `src/domains/portfolio_accounting/intraday_alerts.py` | 1 | intraday_stop_alerts | portfolio_accounting |
| `intraday_stream` | `src/gates/workflows/intraday_stream.py` | 1,2 | intraday_stream_leases | gates |
| `live_quotes` | `src/domains/market_data/live_quotes.py` | 1 | live_quotes | market_data |
| `risk_reservations` | `src/domains/portfolio_engine/risk_reservations.py` | 1 | risk_reservations | portfolio_engine |
| `market` | `src/domains/market_data/legacy_schema.py` (legacy bridge; owner schemas in market_data, reference_data, indicators and research) | 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17 | corporate_action_events, corporate_action_watermark, data_quality_events, market_bars, market_fetch_coverage, market_fetch_coverage_v16, market_history_revisions, market_index_quote_history, market_index_quotes, market_indicators, reference_instruments, reference_token_observations, universe_build_state, universe_exit_eligibility, universe_exit_eligibility_v15, universe_membership, universe_snapshot_members, universe_snapshots | compatibility bridge only; current table ownership is split across domains |
| `research_pipeline` | `src/domains/research/pipeline_repository.py` | 1,2,3 | research_pipeline_stages, research_pipelines | research |
| `portfolio_sync` | `src/gates/workflows/portfolio_sync.py` | 1,2 | portfolio_setups, reconciliation_discrepancies | gates/workflows/portfolio_sync |
| `research` | `src/domains/research/repository.py` | 1,2,3 | research_daily_scores, research_lineage, research_percentile_snapshots, research_percentiles, research_weekly_rankings | research |
| `catalog` | `src/domains/artifacts/catalog.py` | 1,2,3 | catalog_artifacts, catalog_invalidations, catalog_lineage, catalog_publications, catalog_tombstones | artifacts |
| `indicator_node_cache` | `src/domains/indicators/node_cache.py` | 1,2 | indicator_node_cache | indicators |
| `ops` | `src/domains/operations/jobs.py` | 1,2,3 | ops_job_events, ops_jobs | operations |
| `broker_orders` | `src/domains/execution/order_repository.py` | 1,2,3 | broker_basket_orders, broker_baskets, broker_execution_events, broker_orders | execution |
| `kite_accounts` | `src/domains/execution/accounts.py` | 1,2 | kite_accounts, strategy_portfolios | execution |
| `ledger` | `src/domains/portfolio_accounting/ledger.py` | 1,2,3,4 | ledger_accounts, ledger_commands, ledger_events, ledger_valuation_snapshots | portfolio_accounting |
| `portfolio_risk_config` | `src/domains/portfolio_engine/risk_config.py` | 1 | portfolio_risk_config | portfolio_engine |
| `strategy_definitions` | `src/domains/strategies/definitions.py` | 1 | strategy_definitions, strategy_revisions | strategies |

### Non-domain Python entry and support files

| Current path | Target/disposition | Owner | Phase/status |
|---|---|---|---|
| `run.py` | Keep public path; delegate app construction and server startup to `src.gates.app` | gates / stable entry | Phase 2 |
| `db.py` | Audit remaining callers; retire only when unused | legacy database facade | Phase 6 |
| `test.py` | Audit obsolete `run.app` and service imports before retirement | legacy test entry | Phase 6 |
| `local_secrets.example.py` | Keep as configuration example | repository config | Keep; do not place credentials here |
| `local_secrets.py` | Protected runtime secret file; do not read, move, or alter | external configuration | Out of scope |
| `tools/strategy1_backtest.py`, `tools/strategy4_backtest.py`, `tools/strategy4_event_study.py`, `tools/strategy4_pyramid_diagnostics.py`, `tools/strategy4_supertrend_comparison.py` | Keep CLI options stable; update imports to public domain APIs | backtesting / strategies | Phases 4 and 6 |
| `tools/verify_phase_repairs.py` | Keep audit behavior and update imports only when source paths move | release checks | Phases 2 and 6 |

## Current Python source disposition

Every Python file currently present below `src/` is listed. Imported/exported symbol details and line references are in the refreshed AST source inventory. Test candidates are exact same-basename modules; broader workflow tests remain required where no focused test exists.

| Current source | Planned destination | Owner | Focused verification | Phase/status |
|---|---|---|---|---|
| `src/__init__.py` | `src/domains/__init__.py/__init__.py` | __init__.py | No same-name test; retain workflow regressions | Merge legacy package into target domain |
| `src/domains/__init__.py` | `src/domains/__init__.py` | domain package root | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/artifacts/__init__.py` | `src/domains/artifacts/__init__.py` | artifacts | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/artifacts/catalog.py` | `src/domains/artifacts/catalog.py` | artifacts | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/artifacts/publication.py` | `src/domains/artifacts/publication.py` | artifacts | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/backtesting/__init__.py` | `src/domains/backtesting/__init__.py` | backtesting public API | `tests/backtesting/test_run_store.py` | Curated store export |
| `src/domains/backtesting/api.py` | `src/domains/backtesting/api.py` | backtesting API | `tests/backtesting/test_backtesting.py`, `tests/backtesting/test_run_store.py` | Curated replay result/manifest/step/fill API, neutral portfolio-engine port, and run store |
| `src/domains/backtesting/repository.py` | `src/domains/backtesting/repository.py` | backtesting repository | `tests/backtesting/test_run_store.py` | Owns version-1 `backtest` schema and run-index reads/writes/deletes |
| `src/domains/backtesting/simulation.py` | `src/domains/backtesting/simulation.py` | backtesting calculation core | `tests/backtesting/test_backtesting.py`, `tests/test_review_regressions.py`, `tests/portfolio_engine/test_portfolio_engine.py` | Framework-free replay/result logic moved from the legacy package; depends on portfolio public API and kernel only |
| `src/domains/execution/__init__.py` | `src/domains/execution/__init__.py` | execution public API | No same-name test; retain auth integration coverage | Curated exports for provider credentials and auth service |
| `src/domains/execution/accounts.py` | `src/domains/execution/accounts.py` | execution account service | `integration_tests/execution/test_kite_accounts.py`, `integration_tests/gates/test_portfolio_sync.py` | Moved from legacy gateway in Step 89; preserves kite_accounts versions 1–2; strategy allow-list injected |
| `src/domains/execution/api.py` | `src/domains/execution/api.py` | execution API | `tests/domains/execution/test_kite_profiles.py`, `integration_tests/gates/test_kite_auth_callback.py` | Public execution-provider authentication contracts |
| `src/domains/execution/broker_adapter.py` | `src/domains/execution/broker_adapter.py` | execution broker protocol/provider adapter | `integration_tests/gates/test_broker_execution.py`, `tests/test_phase_completion_repairs.py` | Moved from the mixed order service in Step 90; workflow now lives in gates; legacy package removed in Step 94 |
| `src/domains/execution/kite_auth.py` | `src/domains/execution/kite_auth.py` | execution | `tests/domains/execution/test_kite_profiles.py`, `integration_tests/gates/test_kite_auth_callback.py` | Credentials and token lifecycle moved from application; gate adapters consume public API |
| `src/domains/execution/order_repository.py` | `src/domains/execution/order_repository.py` | execution order repository | `tests/domains/execution/test_order_repository.py`, `integration_tests/gates/test_broker_execution.py` | Added Step 94; owns unchanged broker_orders schema versions 1–3, order/basket/event persistence and state transitions |
| `src/domains/execution/streaming_provider.py` | `src/domains/execution/streaming_provider.py` | domain/gate package | No same-name test; retain workflow regressions | Current source; see ownership inventory for disposition |
| `src/domains/indicators/__init__.py` | `src/domains/indicators/__init__.py` | indicators | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/indicators/api.py` | `src/domains/indicators/api.py` | indicators | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/indicators/dag.py` | `src/domains/indicators/dag.py` | indicators | `tests/domains/indicators/test_dag.py` | In target tree; verify public API and dependencies |
| `src/domains/indicators/momentum_quality.py` | `src/domains/indicators/momentum_quality.py` | indicators | `integration_tests/gates/test_momentum_quality.py` | In target tree; verify public API and dependencies |
| `src/domains/indicators/node_cache.py` | `src/domains/indicators/node_cache.py` | indicators | `tests/domains/indicators/test_node_cache.py` | In target tree; verify public API and dependencies |
| `src/domains/indicators/registry.py` | `src/domains/indicators/registry.py` | indicators | `tests/domains/indicators/test_registry.py` | In target tree; verify public API and dependencies |
| `src/domains/indicators/relative_strength.py` | `src/domains/indicators/relative_strength.py` | indicators | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/market_data/__init__.py` | `src/domains/market_data/__init__.py` | market_data | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/market_data/api.py` | `src/domains/market_data/api.py` | market_data | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/market_data/history_repository.py` | `src/domains/market_data/history_repository.py` | market_data | `tests/market_data/test_fetch_coverage.py`, `tests/market_data/test_repository_migrations.py` | Owner persistence; legacy DDL bridge still needs deduplication |
| `src/domains/market_data/index_quotes.py` | `src/domains/market_data/index_quotes.py` | market_data | `tests/market_data/test_repository_migrations.py`, `tests/application/test_market_repository.py` | Owner extraction; aggregate caller audit remains |
| `src/domains/market_data/legacy_schema.py` | `src/domains/market_data/legacy_schema.py` | market_data migration bridge | `tests/market_data/test_repository_migrations.py`, `tests/reference_data/test_repository_migrations.py` | Compatibility upgrade chain for existing databases; duplicate historical DDL cleanup remains |
| `src/domains/market_data/live_quotes.py` | `src/domains/market_data/live_quotes.py` | market_data | `tests/market_data/test_live_quotes.py` | Account-scoped quote persistence and freshness rules |
| `src/domains/market_data/providers.py` | `src/domains/market_data/providers.py` | market_data | `tests/market_data/test_market_provider_adapters.py`, `integration_tests/gates/test_market_jobs.py` | Historical bars, instrument list, and quote provider adapters |
| `src/domains/market_data/repository.py` | `src/domains/market_data/repository.py` | market_data | `tests/market_data/test_repository_migrations.py`, `tests/application/test_market_repository.py` | Domain repository; broad aggregate API audit remains |
| `src/domains/market_data/schema.py` | `src/domains/market_data/schema.py` | market_data | `tests/market_data/test_repository_migrations.py` | Owner migration in place; legacy bridge retained |
| `src/domains/operations/__init__.py` | `src/domains/operations/__init__.py` | operations | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/operations/jobs.py` | `src/domains/operations/jobs.py` | operations | `tests/domains/operations/test_jobs.py` | In target tree; verify public API and dependencies |
| `src/domains/operations/worker.py` | `src/domains/operations/worker.py` | operations | `tests/domains/operations/test_worker.py` | In target tree; verify public API and dependencies |
| `src/domains/portfolio_accounting/__init__.py` | `src/domains/portfolio_accounting/__init__.py` | portfolio_accounting | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/portfolio_accounting/api.py` | `src/domains/portfolio_accounting/api.py` | portfolio_accounting | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/portfolio_accounting/intraday_alerts.py` | `src/domains/portfolio_accounting/intraday_alerts.py` | portfolio_accounting | `tests/portfolio_accounting/test_intraday_alerts.py` | Fill-free ATR stop evaluation and alert read model |
| `src/domains/portfolio_accounting/ledger.py` | `src/domains/portfolio_accounting/ledger.py` | portfolio-accounting persistence | `tests/domains/portfolio_accounting/test_ledger.py`, `integration_tests/portfolio_accounting/test_ledger_opening_positions.py`, `tests/portfolio_accounting/test_intraday_alerts.py` | Moved in Step 91; preserves ledger versions 1–4; legacy execution-gateway package retired in Step 94 |
| `src/domains/portfolio_accounting/portfolio_performance.py` | `src/domains/portfolio_accounting/portfolio_performance.py` | portfolio_accounting | `tests/domains/portfolio_accounting/test_portfolio_performance.py` | In target tree; verify public API and dependencies |
| `src/domains/portfolio_engine/__init__.py` | `src/domains/portfolio_engine/__init__.py` | portfolio_engine | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/portfolio_engine/api.py` | `src/domains/portfolio_engine/api.py` | portfolio_engine | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/portfolio_engine/proposal_store.py` | `src/domains/portfolio_engine/proposal_store.py` | portfolio_engine repository | `tests/portfolio_engine/test_proposal_store.py`, `tests/test_action_lifecycle.py` | Owns `actions` schema namespace, append-only proposal events, recovery projection, status decisions, and proposal queries |
| `src/domains/portfolio_engine/risk_config.py` | `src/domains/portfolio_engine/risk_config.py` | portfolio_engine risk configuration | `tests/domains/portfolio_engine/test_risk_config.py`, `integration_tests/gates/test_managed_risk.py` | Moved in Step 88; preserves portfolio_risk_config version 1 |
| `src/domains/portfolio_engine/risk_reservations.py` | `src/domains/portfolio_engine/risk_reservations.py` | portfolio_engine persistence | `tests/portfolio_engine/test_risk_reservations.py`, `integration_tests/gates/test_managed_risk.py` | Owns the unchanged risk_reservations version-1 schema and connection-scoped reservation reads/writes; the gate supplies the shared cross-owner transaction |
| `src/domains/reference_data/__init__.py` | `src/domains/reference_data/__init__.py` | reference_data | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/reference_data/api.py` | `src/domains/reference_data/api.py` | reference_data | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/reference_data/nse_provider.py` | `src/domains/reference_data/nse_provider.py` | reference_data provider | `integration_tests/gates/test_market_jobs.py`, `integration_tests/gates/test_corporate_actions.py` | Domain provider; gate workflows own scheduling |
| `src/domains/reference_data/repository.py` | `src/domains/reference_data/repository.py` | reference_data | `tests/reference_data/test_repository_migrations.py`, `integration_tests/gates/test_reference_tokens.py` | Domain persistence; gate aggregate retains composite use cases |
| `src/domains/reference_data/schema.py` | `src/domains/reference_data/schema.py` | reference_data | `tests/reference_data/test_repository_migrations.py` | Owner migration in place; legacy bridge retained |
| `src/domains/research/__init__.py` | `src/domains/research/__init__.py` | research package API | No same-name test; repository regressions cover behavior | Research persistence ownership introduced in Step 82 |
| `src/domains/research/api.py` | `src/domains/research/api.py` | research public API | No same-name test; repository regressions cover behavior | Curated `ResearchRepository` export |
| `src/domains/research/calculations.py` | `src/domains/research/calculations.py` | research calculations | `tests/domains/research/test_calculations.py`, `tests/test_sector_rankings.py`, `tests/test_research_anomalies.py` | Sector normalization, return correlation/clusters, anomaly scoring, and weekly aggregation moved from `ResearchJobs` in Step 83 |
| `src/domains/research/pipeline_repository.py` | `src/domains/research/pipeline_repository.py` | research pipeline persistence | `tests/domains/research/test_pipeline_repository.py`, `tests/test_research_pipeline_jobs.py` | Owns the unchanged research_pipeline namespace and versions 1-3; SQL moved from the application coordinator in Step 85 |
| `src/domains/research/repository.py` | `src/domains/research/repository.py` | research persistence | `tests/domains/research/test_repository.py`, `tests/test_research_bulk_rebuild.py` | Owns schema versions 1-3 and all daily-score, weekly-ranking, percentile-cache, and lineage SQL |
| `src/domains/strategies/__init__.py` | `src/domains/strategies/__init__.py` | strategies | No same-name test; retain workflow regressions | In target tree; verify public API and dependencies |
| `src/domains/strategies/api.py` | `src/domains/strategies/api.py` | strategies public API | `tests/domains/strategies/test_ranking_patterns.py`, `tests/test_strategy4_v4_contract.py` | Public calculations consumed by gates |
| `src/domains/strategies/definitions.py` | `src/domains/strategies/definitions.py` | strategies | `tests/gates/test_strategy_definitions.py`, `tests/test_strategy_revisions.py` | Domain validation/persistence; gate adapter remains |
| `src/domains/strategies/identity.py` | `src/domains/strategies/identity.py` | strategies | `tests/application/test_strategy_runtime.py`, `tests/test_strategy_revisions.py` | Owns canonical IDs, removed strategy IDs, and legacy alias resolution |
| `src/domains/strategies/momentum_quality.py` | `src/domains/strategies/momentum_quality.py` | strategies | `integration_tests/gates/test_momentum_quality.py` | In target tree; verify public API and dependencies |
| `src/domains/strategies/positional_trend.py` | `src/domains/strategies/positional_trend.py` | strategies | `tests/test_strategy4_v4_contract.py`, `tests/test_strategy4_integration.py` | Strategy calculations; orchestration stays in gates |
| `src/domains/strategies/positional_trend_backtest.py` | `src/domains/strategies/positional_trend_backtest.py` | strategies | `tests/test_strategy4_backtest.py`, `tests/test_strategy4_v4_contract.py`, `tests/test_strategy4_integration.py` | Strategy 4 policy and next-open portfolio replay moved from application in Step 80 |
| `src/domains/strategies/ranking_patterns.py` | `src/domains/strategies/ranking_patterns.py` | strategies | `tests/domains/strategies/test_ranking_patterns.py` | In target tree; verify public API and dependencies |
| `src/gates/__init__.py` | `src/gates/__init__.py` | gates | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/app.py` | `src/gates/app.py` | gates | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/backtesting_adapter.py` | `src/gates/backtesting_adapter.py` | gates adapter | `tests/backtesting/test_backtesting.py`, `tests/portfolio_engine/test_portfolio_engine.py`, `tests/test_review_regressions.py` | Adapts portfolio-engine evaluation/assumption types to the neutral backtesting port |
| `src/gates/cli.py` | `src/gates/cli.py` | gates | `tests/gates/test_cli.py` | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/composition.py` | `src/gates/composition.py` | gates | `tests/application/test_composition.py` | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/__init__.py` | `src/gates/http/__init__.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/actions.py` | `src/gates/http/actions.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/backtest.py` | `src/gates/http/backtest.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/broker.py` | `src/gates/http/broker.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/dashboard.py` | `src/gates/http/dashboard.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/indicators.py` | `src/gates/http/indicators.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/kite_accounts.py` | `src/gates/http/kite_accounts.py` | gates/http | `integration_tests/execution/test_kite_accounts.py` | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/kite_auth.py` | `src/gates/http/kite_auth.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/market.py` | `src/gates/http/market.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/operations.py` | `src/gates/http/operations.py` | gates/http | `tests/gates/test_operations.py` | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/pipeline.py` | `src/gates/http/pipeline.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/portfolio.py` | `src/gates/http/portfolio.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/positional_trend.py` | `src/gates/http/positional_trend.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/reference.py` | `src/gates/http/reference.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/research.py` | `src/gates/http/research.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/strategies.py` | `src/gates/http/strategies.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/universe.py` | `src/gates/http/universe.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/http/wiki.py` | `src/gates/http/wiki.py` | gates/http | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/indicator_implementations.py` | `src/gates/indicator_implementations.py` | gates adapter | `tests/domains/indicators/test_registry.py`, `tests/test_strategy4_integration.py` | Gate wires public indicator and strategy APIs |
| `src/gates/momentum_quality.py` | `src/gates/momentum_quality.py` | gates | `integration_tests/gates/test_momentum_quality.py` | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/operations.py` | `src/gates/operations.py` | gates | `tests/gates/test_operations.py` | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/payloads.py` | `src/gates/payloads.py` | gates payload parsing | `tests/test_research_bulk_rebuild.py`, gate request regressions | Moved from application in Step 84; command parsing belongs at the request/workflow boundary |
| `src/gates/release_gates.py` | `src/gates/release_gates.py` | gates | `tests/gates/test_release_gates.py` | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/repositories.py` | `src/gates/repositories.py` | gates repository aggregate | `tests/application/test_market_repository.py`, `integration_tests/gates/test_session_coverage.py`, `integration_tests/gates/test_corporate_actions.py` | Cross-domain transaction/query adapter; narrow API audit remains |
| `src/gates/runtime.py` | `src/gates/runtime.py` | gates | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/security.py` | `src/gates/security.py` | gates | No same-name test; retain workflow regressions | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/session_coverage.py` | `src/gates/session_coverage.py` | gates | `integration_tests/gates/test_session_coverage.py` | In target tree; remaining legacy edges are exact-allowlisted |
| `src/gates/strategy_definitions.py` | `src/domains/strategies/definitions.py` + `src/gates/strategy_validation.py` | strategies / gates adapter | `tests/gates/test_strategy_definitions.py` | Domain owns persistence and rules; gate facade retains constructor compatibility |
| `src/gates/strategy_runtime.py` | `src/gates/strategy_runtime.py` | gates cross-domain runtime | `tests/gates/test_strategy_runtime.py`, `integration_tests/execution/test_kite_accounts.py` | StrategyRuntime moved from application in Step 81; uses public indicator/strategy APIs and gate-owned validators/implementations |
| `src/gates/strategy_validation.py` | `src/gates/strategy_validation.py` | gates adapter | `tests/gates/test_strategy_definitions.py` | Adapts indicators and gate implementation registry to domain validator |
| `src/gates/workflows/__init__.py` | `src/gates/workflows/__init__.py` | gates workflow package | No same-name test; retain workflow regressions | Package namespace for cross-domain workflows |
| `src/gates/workflows/backtesting.py` | `src/gates/workflows/backtesting.py` | gates cross-domain workflow | `tests/backtesting/test_backtesting.py`, `tests/backtesting/test_run_store.py`, `tests/test_review_regressions.py` | Moved from application in Step 79; run persistence is delegated to `domains/backtesting`; market, research, publication, and Strategy 4 coordination remain here |
| `src/gates/workflows/broker_orders.py` | `src/gates/workflows/broker_orders.py` | gates cross-domain broker workflow | `integration_tests/gates/test_broker_execution.py`, `integration_tests/gates/test_broker_web.py` | Moved from the legacy execution gateway in Step 94; consumes execution repository and public portfolio, execution, risk, and market APIs |
| `src/gates/workflows/corporate_actions.py` | `src/gates/workflows/corporate_actions.py` | gates workflow | `tests/gates/test_corporate_actions.py`, `integration_tests/gates/test_corporate_actions.py` | Gate-owned cross-domain lifecycle and adjustment |
| `src/gates/workflows/index_poller.py` | `src/gates/workflows/index_poller.py` | gates lifecycle/workflow | `integration_tests/gates/test_index_poller.py`, `tests/gates/test_cli.py` | Owns durable scheduling and background lifecycle for quote jobs |
| `src/gates/workflows/intraday_stream.py` | `src/gates/workflows/intraday_stream.py` | gates workflow/lifecycle | `integration_tests/gates/test_live_quote_stream.py` | Owns durable lease state for supervised live stream |
| `src/gates/workflows/liquidity_universe.py` | `src/gates/workflows/liquidity_universe.py` | gates | `integration_tests/gates/test_liquidity_universe_job.py` | Moved from application in Step 60 |
| `src/gates/workflows/live_quote_stream.py` | `src/gates/workflows/live_quote_stream.py` | gates workflow | `integration_tests/gates/test_live_quote_stream.py` | Broker session/market identity coordination and stream lifecycle |
| `src/gates/workflows/managed_risk.py` | `src/gates/workflows/managed_risk.py` | gates risk orchestration | `integration_tests/gates/test_managed_risk.py`, `tests/test_action_lifecycle.py` | Moved from application in Step 86; validates ledger/market/portfolio constraints and delegates reservation state through a caller-owned transaction |
| `src/gates/workflows/market_ingestion.py` | `src/gates/workflows/market_ingestion.py` | gates workflow | `integration_tests/gates/test_market_ingestion.py`, `tests/test_review_regressions.py` | Redacted raw evidence and normalized artifact publication with lineage |
| `src/gates/workflows/market_jobs.py` | `src/gates/workflows/market_jobs.py` | gates workflow/job handlers | `integration_tests/gates/test_market_jobs.py`, `tests/test_phase2_behavioral.py` | Coordinates provider calls, market persistence, coverage, publication, and alert polling |
| `src/gates/workflows/market_refresh.py` | `src/gates/workflows/market_refresh.py` | gates workflow | `integration_tests/gates/test_market_refresh.py`, `integration_tests/gates/test_pipeline_preparation.py` | Coordinates refresh scheduling, market coverage, and held instruments |
| `src/gates/workflows/pipeline_preparation.py` | `src/gates/workflows/pipeline_preparation.py` | gates workflow | `integration_tests/gates/test_pipeline_preparation.py` | Coordinates cross-domain manual data prerequisites |
| `src/gates/workflows/portfolio_actions.py` | `src/gates/workflows/portfolio_actions.py` | gates cross-domain workflow | `tests/test_action_lifecycle.py`, `tests/test_strategy4_integration.py`, `tests/portfolio_engine/test_proposal_store.py` | ActionJobs moved in Step 76; proposal storage is delegated to portfolio_engine; market/research/accounting/artifact/execution sequencing stays here |
| `src/gates/workflows/portfolio_sync.py` | `src/gates/workflows/portfolio_sync.py` | gates workflow | `integration_tests/gates/test_portfolio_sync.py` | Coordinates account, ledger, strategy IDs, and market identity |
| `src/gates/workflows/positional_trend.py` | `src/gates/workflows/positional_trend.py` | gates workflow | `integration_tests/gates/test_momentum_quality.py`, `tests/test_strategy4_integration.py` | Coordinates market, strategy, runtime, and artifacts |
| `src/gates/workflows/positional_trend_backtest_inputs.py` | `src/gates/workflows/positional_trend_backtest_inputs.py` | gates composite input adapter | `tests/test_strategy4_backtest.py`, `tests/test_phase_completion_repairs.py`, `tests/test_strategy4_event_study.py` | CSV/database input assembly and benchmark reader moved from application in Step 80; raw cross-owner SQL remains a repository extraction candidate |
| `src/gates/workflows/research.py` | `src/gates/workflows/research.py` | gates research workflow | `tests/domains/research/test_calculations.py`, `tests/domains/research/test_repository.py`, `tests/test_research_bulk_rebuild.py`, `integration_tests/gates/test_pipeline_preparation.py` | ResearchJobs moved from application in Step 84; coordinates market/strategy inputs, research persistence, artifacts, and durable workflow calls |
| `src/gates/workflows/research_pipeline.py` | `src/gates/workflows/research_pipeline.py` | gates research pipeline workflow | `tests/test_research_pipeline_jobs.py`, `tests/test_parity_assessment.py`, `tests/gates/test_cli.py` | Moved from application in Step 85; date/session validation and cross-domain job lifecycle coordinate through research pipeline storage API |
| `src/gates/workflows/trading_calendar.py` | `src/gates/workflows/trading_calendar.py` | gates workflow | `integration_tests/gates/test_session_coverage.py` | Cross-domain session/read model |
| `src/gates/workflows/universe.py` | `src/gates/workflows/universe.py` | gates workflow | `tests/gates/test_universe_jobs.py`, `tests/test_phase2_behavioral.py`, `tests/test_phase_completion_repairs.py` | Coordinates reference snapshots, market sessions, and exit eligibility |
| `src/platform_kernel/__init__.py` | `src/platform_kernel/__init__.py` | platform_kernel | No same-name test; retain workflow regressions | Retain; verify minimal neutral foundation |
| `src/platform_kernel/api.py` | `src/platform_kernel/api.py` | platform_kernel | No same-name test; retain workflow regressions | Retain; verify minimal neutral foundation |
| `src/platform_kernel/artifacts.py` | `src/platform_kernel/artifacts.py` | platform_kernel | No same-name test; retain workflow regressions | Retain; verify minimal neutral foundation |
| `src/platform_kernel/contracts.py` | `src/platform_kernel/contracts.py` | platform_kernel | No same-name test; retain workflow regressions | Retain; verify minimal neutral foundation |
| `src/platform_kernel/errors.py` | `src/platform_kernel/errors.py` | platform_kernel | No same-name test; retain workflow regressions | Retain; verify minimal neutral foundation |
| `src/platform_kernel/ports.py` | `src/platform_kernel/ports.py` | platform_kernel | No same-name test; retain workflow regressions | Retain; verify minimal neutral foundation |
| `src/platform_kernel/security.py` | `src/platform_kernel/security.py` | platform_kernel | No same-name test; retain workflow regressions | Retain; verify minimal neutral foundation |
| `src/platform_kernel/sqlite.py` | `src/platform_kernel/sqlite.py` | platform_kernel | No same-name test; retain workflow regressions | Retain; verify minimal neutral foundation |
## Test source disposition

Current layout audit (2026-10-03): `tests/` contains 86 test modules, each mapping to exactly one existing `src/` module by relative path and basename. There are zero unmatched test modules and no duplicate mappings. The 129-module source tree has 86 focused test modules; source modules without tests are not given empty placeholders. The content audit split or moved mixed-owner cases for accounting ledger/API, strategy API/runtime identity, strategy/gate momentum scoring, indicator DAG/registry, portfolio performance/ledger dependency, backtesting adapter, and gate-owned migration composition. Domain test modules have no direct gate imports; cross-domain application scenarios belong under matching gate modules. `tests/integration/`, `tests/architecture/`, and the root `integration_tests/` are not part of the layout. The repository-wide import-boundary verifier is `tools/verify_import_boundaries.py`. `pyproject.toml` and `make test` target only `tests/`. This is a structural audit, not a full test run; pytest was not run during this consolidation.

Historical test-disposition plan (superseded by the current layout note below): the original inventory had 68 modules under `tests/` and 30 under `integration_tests/`. Those entries document where cases originated; the completed tree has no integration subtree. Current rule: `src/<path>/<module>.py` maps to `tests/<path>/test_<module>.py`, and each test file contains only tests for its matching source module. Cross-domain behavior belongs with its owning gate source module. There is no `tests/integration/` exception.

| Current test path | Verification owner | Status |
|---|---|---|
| `integration_tests/application/test_app_startup.py` | `src/gates/app.py` | Rename/move to `tests/gates/test_app.py` |
| `integration_tests/application/test_artifact_lineage.py` | artifact publication/catalog APIs | Split/rename to `tests/domains/artifacts/test_publication.py` and `test_catalog.py` as assertions permit |
| `integration_tests/application/test_market_web.py` | `src/gates/http/market.py` | Rename/move to `tests/gates/http/test_market.py` |
| `integration_tests/application/test_publication_recovery.py` | `src/domains/artifacts/publication.py` | Rename/move to `tests/domains/artifacts/test_publication.py`; split only if it exercises an independent gate workflow |
| `integration_tests/execution/test_kite_accounts.py` | `src/domains/execution/accounts.py` + `src/gates/workflows/portfolio_sync.py` | Split into `tests/domains/execution/test_accounts.py` and `tests/gates/workflows/test_portfolio_sync.py` |
| `integration_tests/gates/test_broker_execution.py` | `src/gates/workflows/broker_orders.py` + execution APIs | Rename/move to `tests/gates/workflows/test_broker_orders.py` |
| `integration_tests/gates/test_broker_web.py` | `src/gates/http/broker.py` | Rename/move to `tests/gates/http/test_broker.py` |
| `integration_tests/gates/test_corporate_actions.py` | `src/gates/workflows/corporate_actions.py` | Rename/move to `tests/gates/workflows/test_corporate_actions.py` |
| `integration_tests/gates/test_dashboard_web.py` | `src/gates/http/dashboard.py` | Rename/move to `tests/gates/http/test_dashboard.py` |
| `integration_tests/gates/test_index_poller.py` | `src/gates/workflows/index_poller.py` | Rename/move to `tests/gates/workflows/test_index_poller.py` |
| `integration_tests/gates/test_intraday_alerts.py` | `src/domains/portfolio_accounting/intraday_alerts.py` + alert gate workflow | Rename/split into `tests/domains/portfolio_accounting/test_intraday_alerts.py` and `tests/gates/workflows/test_intraday_alerts.py` |
| `integration_tests/gates/test_kite_auth_callback.py` | `src/gates/http/kite_auth.py` | Rename/move to `tests/gates/http/test_kite_auth.py` |
| `integration_tests/gates/test_kite_profile_isolation.py` | `src/gates/http/kite_accounts.py` + execution accounts | Rename/split into `tests/gates/http/test_kite_accounts.py` and `tests/domains/execution/test_accounts.py` |
| `integration_tests/gates/test_liquidity_universe_job.py` | `src/gates/workflows/liquidity_universe.py` | Rename/move to `tests/gates/workflows/test_liquidity_universe.py` |
| `integration_tests/gates/test_live_quote_stream.py` | `src/gates/workflows/live_quote_stream.py` + `intraday_stream.py` | Rename/split into `tests/gates/workflows/test_live_quote_stream.py` and `test_intraday_stream.py` |
| `integration_tests/gates/test_managed_risk.py` | `src/gates/workflows/managed_risk.py` | Rename/move to `tests/gates/workflows/test_managed_risk.py` |
| `integration_tests/gates/test_market_coverage.py` | `src/gates/session_coverage.py` + trading calendar | Rename/move to `tests/gates/workflows/test_session_coverage.py` |
| `integration_tests/gates/test_market_ingestion.py` | `src/gates/workflows/market_ingestion.py` | Rename/move to `tests/gates/workflows/test_market_ingestion.py` |
| `integration_tests/gates/test_market_jobs.py` | `src/gates/workflows/market_jobs.py` | Rename/move to `tests/gates/workflows/test_market_jobs.py` |
| `integration_tests/gates/test_market_refresh.py` | `src/gates/workflows/market_refresh.py` | Rename/move to `tests/gates/workflows/test_market_refresh.py` |
| `integration_tests/gates/test_momentum_quality.py` | `src/gates/workflows/positional_trend.py` + indicator/strategy APIs | Rename/split into owner unit tests and `tests/gates/workflows/test_positional_trend.py` |
| `integration_tests/gates/test_operations_progress.py` | `src/domains/operations/worker.py` + operations HTTP | Rename/split into `tests/domains/operations/test_worker.py` and `tests/gates/http/test_operations.py` |
| `integration_tests/gates/test_pipeline_preparation.py` | `src/gates/workflows/pipeline_preparation.py` | Rename/move to `tests/gates/workflows/test_pipeline_preparation.py` |
| `integration_tests/gates/test_portfolio_sync.py` | `src/gates/workflows/portfolio_sync.py` | Rename/move to `tests/gates/workflows/test_portfolio_sync.py` |
| `integration_tests/gates/test_portfolio_web.py` | `src/gates/http/portfolio.py` | Rename/move to `tests/gates/http/test_portfolio.py` |
| `integration_tests/gates/test_reference_tokens.py` | `src/gates/http/reference.py` + reference domain API | Rename/split into `tests/gates/http/test_reference.py` and reference-owner tests |
| `integration_tests/gates/test_reference_web.py` | `src/gates/http/reference.py` | Rename/move to `tests/gates/http/test_reference.py`; consolidate with token route coverage |
| `integration_tests/gates/test_session_coverage.py` | `src/gates/session_coverage.py` | Rename/move to `tests/gates/test_session_coverage.py` |
| `integration_tests/portfolio_accounting/test_ledger_opening_positions.py` | `src/domains/portfolio_accounting/ledger.py` | Rename/move to `tests/domains/portfolio_accounting/test_ledger.py`; merge with existing ledger suite |
| `integration_tests/test_application_shell.py` | `src/gates/app.py` | Rename/move to `tests/gates/test_app.py`; merge app-startup assertions |
| `tests/application/test_composition.py` | `src/gates/composition.py` | Rename/move to `tests/gates/test_composition.py` |
| `tests/application/test_market_repository.py` | `src/gates/repositories.py` and market owner repositories | Split/rename into tests matching each repository source module and gate aggregate |
| `tests/application/test_pipeline_jobs.py` | `src/gates/workflows/research_pipeline.py` | Rename/move to `tests/gates/workflows/test_research_pipeline.py` |
| `tests/architecture/test_import_boundaries.py` | architecture | Historical location; now `tools/verify_import_boundaries.py` because it is a repository-wide check, not a test for one source module |
| `tests/backtesting/test_backtesting.py` | backtesting | Active |
| `tests/backtesting/test_run_store.py` | backtesting | Active |
| `tests/domains/execution/test_kite_profiles.py` | domains/execution | Active source-owner regression; rename to the matching source module during the unified test-tree phase |
| `tests/domains/execution/test_order_repository.py` | domains/execution | Active source-owner regression; rename to the matching source module during the unified test-tree phase |
| `tests/domains/execution/test_streaming_provider.py` | domains/execution | Active source-owner regression; rename to the matching source module during the unified test-tree phase |
| `tests/domains/indicators/test_dag.py` | domains/indicators | Active |
| `tests/domains/indicators/test_dag_executor.py` | domains/indicators | Active |
| `tests/domains/indicators/test_dag_output.py` | domains/indicators | Active |
| `tests/domains/indicators/test_node_cache.py` | domains/indicators | Active |
| `tests/domains/indicators/test_registry.py` | domains/indicators | Active |
| `tests/domains/operations/test_durable_jobs.py` | domains/operations | Active |
| `tests/domains/operations/test_jobs.py` | domains/operations | Active |
| `tests/domains/operations/test_worker.py` | domains/operations | Active |
| `tests/domains/portfolio_accounting/test_ledger.py` | domains/portfolio_accounting | Active source-owner regression; rename to the matching source module during the unified test-tree phase |
| `tests/domains/portfolio_accounting/test_portfolio_performance.py` | domains/portfolio_accounting | Active |
| `tests/domains/portfolio_engine/test_risk_config.py` | domains/portfolio_engine | Active source-owner regression; rename to the matching source module during the unified test-tree phase |
| `tests/domains/research/test_calculations.py` | domains/research | Added in Step 83; direct calculation regressions |
| `tests/domains/research/test_pipeline_repository.py` | domains/research | Added in Step 85; migration and stage-state repository regressions |
| `tests/domains/research/test_repository.py` | domains/research | Active |
| `tests/domains/strategies/test_ranking_patterns.py` | domains/strategies | Active |
| `tests/gates/test_cli.py` | gates | Active |
| `tests/gates/test_corporate_actions.py` | gates | Active |
| `tests/gates/test_job_progress.py` | gates | Active |
| `tests/gates/test_operations.py` | gates | Active |
| `tests/gates/test_release_gates.py` | gates | Active |
| `tests/gates/test_strategy_definitions.py` | gates | Active |
| `tests/gates/test_strategy_runtime.py` | gates | Moved from application in Step 81; direct StrategyRuntime regressions |
| `tests/gates/test_universe_jobs.py` | gates | Active |
| `tests/market_data/test_fetch_coverage.py` | market_data | Active |
| `tests/market_data/test_live_quotes.py` | market_data | Active |
| `tests/market_data/test_market_provider_adapters.py` | market_data | Active |
| `tests/market_data/test_repository_migrations.py` | market_data | Active |
| `tests/platform_kernel/test_platform_kernel.py` | platform_kernel | Active |
| `tests/platform_kernel/test_sqlite_artifact_store.py` | platform_kernel | Active |
| `tests/platform_kernel/test_sqlite_migrations.py` | platform_kernel | Active |
| `tests/portfolio_accounting/test_intraday_alerts.py` | portfolio_accounting | Moved from mixed top-level module in Step 68 |
| `tests/portfolio_accounting/test_opening_position_projection.py` | portfolio_accounting | Active |
| `tests/portfolio_accounting/test_portfolio_accounting.py` | portfolio_accounting | Active |
| `tests/portfolio_engine/test_atr_exit_rules.py` | portfolio_engine | Active |
| `tests/portfolio_engine/test_portfolio_engine.py` | portfolio_engine | Active |
| `tests/portfolio_engine/test_proposal_store.py` | portfolio_engine | Active |
| `tests/portfolio_engine/test_risk_reservations.py` | portfolio_engine | Added in Step 86; repository and shared-transaction regressions |
| `tests/reference_data/test_liquidity_universe.py` | reference_data | Active |
| `tests/reference_data/test_repository_migrations.py` | reference_data | Active |
| `tests/test_action_lifecycle.py` | `src/gates/workflows/portfolio_actions.py` | Rename/move to `tests/gates/workflows/test_portfolio_actions.py` |
| `tests/test_operations_api.py` | `src/gates/http/operations.py` | Rename/move to `tests/gates/http/test_operations.py` |
| `tests/test_parity_assessment.py` | `src/gates/workflows/research_pipeline.py` | Rename/move to `tests/gates/workflows/test_research_pipeline.py`; merge by behavior |
| `tests/test_phase1_quality_repairs.py` | multiple market/research/indicator modules | Split into tests named for the exact source modules exercised |
| `tests/test_phase2_behavioral.py` | multiple domains and gates | Split into tests named for the exact source modules exercised |
| `tests/test_phase_completion_repairs.py` | multiple domains and gates | Split into tests named for the exact source modules exercised |
| `tests/test_research_anomalies.py` | `src/domains/research/calculations.py` | Rename/move to `tests/domains/research/test_calculations.py`; merge focused cases |
| `tests/test_research_bulk_rebuild.py` | `src/gates/workflows/research.py` | Rename/move to `tests/gates/workflows/test_research.py` |
| `tests/test_research_pipeline.py` | `src/domains/research/pipeline_repository.py` | Rename/move to `tests/domains/research/test_pipeline_repository.py`; merge repository cases |
| `tests/test_research_pipeline_jobs.py` | `src/gates/workflows/research_pipeline.py` | Rename/move to `tests/gates/workflows/test_research_pipeline.py`; merge pipeline cases |
| `tests/test_research_projection_replacement.py` | `src/domains/research/repository.py` | Rename/move to `tests/domains/research/test_repository.py`; merge repository cases |
| `tests/test_review_regressions.py` | multiple owner modules | Split into source-aligned owner and gate workflow tests |
| `tests/test_sector_rankings.py` | strategy/research source modules | Split/rename into tests for the exact ranking and projection modules |
| `tests/test_strategy4_backtest.py` | `src/domains/strategies/positional_trend_backtest.py` | Rename/move to `tests/domains/strategies/test_positional_trend_backtest.py`; gate input assertions split to gate test |
| `tests/test_strategy4_event_study.py` | Strategy 4 simulation and gate inputs | Split into `tests/domains/strategies/test_positional_trend_backtest.py` and matching gate input tests |
| `tests/test_strategy4_integration.py` | `src/gates/workflows/positional_trend.py` | Rename/move to `tests/gates/workflows/test_positional_trend.py` |
| `tests/test_strategy4_supertrend_comparison.py` | `src/domains/strategies/positional_trend_backtest.py` | Rename/move to `tests/domains/strategies/test_positional_trend_backtest.py` |
| `tests/test_strategy4_v4_contract.py` | `src/domains/strategies/positional_trend_backtest.py` | Rename/move to `tests/domains/strategies/test_positional_trend_backtest.py` |
| `tests/test_strategy_revisions.py` | `src/domains/strategies/definitions.py` | Rename/move to `tests/domains/strategies/test_definitions.py` |
| `tests/test_wiki_web.py` | `src/gates/http/wiki.py` | Rename/move to `tests/gates/http/test_wiki.py` |
## Phase gates

| Phase | Current state | Evidence / next work |
|---|---|---|
| 0 — Baseline and manifest | Complete | Current source inventory, route/job/CLI/schema snapshots, support entries, and test paths are recorded. Historical full-suite baseline results are documented; focused direct regression evidence is current through Step 94. The remaining test-tree phase renames 98 modules to source-aligned paths and is not yet complete. |
| 1 — Kernel and boundaries | Complete for current source tree | Shared redaction helpers live in `platform_kernel`; logging/configuration and composition live in gates. Recursive AST checks cover relative, type-only, and literal dynamic imports. Four architecture regression functions report zero violations and zero transitional imports. |
| 2 — Entry points and neutral stateful capabilities | Complete for current source tree | Operations persistence/workers and artifacts are domain-owned; runtime, composition, CLI and HTTP adapters live in gates. `run.py` preserves `create_app`/`main`; `screener-ops` targets `src.gates.cli:main`. Publication recovery behavior still receives domain-level integration coverage. |
| 3 — Reference and market ownership | Owner schemas implemented; cleanup remains | Current market/reference owner schemas and repositories are separated, and fresh databases use those schemas. The historical 17-version `market` upgrade bridge remains for existing databases; duplicate DDL cleanup and broader repository API narrowing remain follow-up work. Composite transactional coordination remains in gates. |
| 4 — Indicators, strategies, research and backtesting | Complete for package ownership; targeted refinements remain | Core calculations, repositories, APIs, and strategy contracts are under domains; cross-domain jobs and runtime coordination are in gates. Research cache fingerprints intentionally change with workflow source relocation. Further public-reader adoption and parity evidence belong to final validation. |
| 5 — Portfolio/accounting/execution | Complete for package ownership; final validation remains | Ledger/accounting, portfolio policy/proposals/risk state, and execution account/order persistence are domain-owned. Broker, sync, managed-risk and portfolio-action coordination live in gates. Preserve final validation for transaction/idempotency and parity contracts. |
| 6 — Cleanup and final proof | In progress | `src/application`, retired top-level domain facades and `src.execution_gateway` are removed; active transition allowlist is empty. Audit root `db.py`/`test.py`, docs/examples/package resources, then run the complete suite and configured lint/type/security/package checks before calling the restructure complete. |

## Out-of-scope protection

Do not rewrite strategy/trading behavior, change schemas/data formats, alter broker safety defaults, delete tokens/secrets/runtime data, call external providers, submit broker orders, or apply `docs/Overhaul_Plan.md` product/UI work as part of this architecture-only restructure. Record unrelated pre-existing worktree edits without replacing them.

## Implementation continuation — 2026-10-03

This batch continued from a worktree with substantial prior migration edits; none were reset. Moved the 14 remaining `src/application/*_web.py` route adapters and the three existing gate web adapters into `src/gates/http/`, then rewrote source, test, integration-test and tool imports. Moved `ApplicationServices` composition and runtime configuration to `src/gates/`, extracted the Flask factory/server lifecycle to `src/gates/app.py`, and reduced root `run.py` to the compatibility entry point. The factory sets Flask's `root_path` to the repository root so root `static/` and `templates/` continue to resolve. Updated the operations script and removed stale composition/runtime boundary exceptions.

Verification so far is static: repository-wide import searches found no references to the old route/composition/runtime module paths; route functions and decorators were moved without handler edits. The full test suite was not rerun in this batch. Confirm dashboard rendering, wiki reads, static assets, all route contracts, app factory configuration, CLI entry points and recursive architecture tests before considering Phase 2 complete.

The same continuation also consolidated the pure `market_data`, `reference_data`, `portfolio_engine`, and `portfolio_accounting` packages under `src/domains/`, rewriting imports across source, tools and tests. The existing portfolio performance service was retained and re-exported from the merged accounting package. These package moves preserve module implementations; `backtesting` remains at its old root until its portfolio-engine dependency is replaced with an injected contract. Static source-path checks and syntax parsing are the only verification performed for this continuation; the earlier 453-test checkpoint predates these moves.

Operations job persistence and worker implementations now live in `src/domains/operations`; in-repository callers use its curated package API, and focused unit tests were moved to `tests/domains/operations`. The old `src/application/jobs.py` and `worker.py` modules are narrow re-export facades pending the final external-caller audit. Five stale operations allowlist entries and the four newly consolidated package roots were removed from the boundary test configuration. AST parsing reports 107 Python modules with no syntax errors and no direct cross-domain imports among modules currently under `src/domains`; these checks do not replace running the test suite.

Artifact catalog and publication services now live under `src/domains/artifacts` with curated package exports. In-repository production and test imports use the new owner package; the two unused five-line application facades were removed in Step 71. Four stale gate-to-application transition entries were removed. The catalog migration namespace and publication behavior are unchanged by relocation.

Strategy revision/snapshot contracts moved into `src/domains/strategies/api.py`; the former `src/strategies` package is now a compatibility facade. Pure positional-trend feature/signal rules moved to `src/domains/strategies/positional_trend.py`. The custom implementation registry moved from `src/indicators/custom` to `src/gates/indicator_implementations.py`, where it composes indicator and strategy functions. Production/test/tool callers and strategy4 monkeypatch paths were updated. Hash inputs now resolve to the new strategy source file; the strategy source bytes are unchanged, while job modules whose source hash includes their own code have changed as a direct result of the path update. Static AST parsing reports 113 Python modules without syntax errors, and the transition map has 48 declared and observed entries with no stale keys. Tests were not run after these moves.

Moved `TradingCalendar` to `src/domains/market_data/calendar.py` and the NSE download client/constants to `src/domains/reference_data/nse_provider.py`. Their public packages export these adapters, and application workflows plus the portfolio HTTP gate import the new owner APIs. The resolved market-gate transition was removed. Current static audit parses 117 Python files including `run.py`, finds no syntax errors or direct cross-domain imports under `src/domains`, and matches all 45 declared gate transition entries to observed imports. Tests were not run after these moves.

Moved the positional-trend signal build workflow to `src/gates/workflows/positional_trend.py`; it coordinates market membership, strategy signals, immutable publication, and strategy runtime without a gate-to-application dependency. The old application path is a one-symbol re-export facade, and the gate composition and HTTP adapter use the new module. Static parsing remains clean and the transition map now has 45 declared and observed entries; tests were not run.

Moved `MarketRepository` and `TrackedInstrument` to `src/domains/market_data/repository.py`, exported them through the market-data package, and updated all production/test/tool callers. `src/application/market_repository.py` is now a compatibility facade. Extracted quote writes and readbacks into `src/domains/market_data/index_quotes.py` as a focused repository concern; `MarketRepository` keeps its existing public methods by inheriting the mixin and retains the existing `market` migration sequence. Removed five gate-to-application repository exceptions. Static audit at this stage covered 119 Python files including `run.py`, found no syntax errors or direct cross-domain imports, and observed all 40 remaining exact gate transition entries. The main repository still mixed several table owners; subsequent extraction is recorded below. Tests were not run.

Extracted the `TrackedInstrument` contract plus instrument identity, token-observation, universe snapshot/membership, and exit-eligibility operations from the central repository into `src/domains/market_data/universe_repository.py`. The public `MarketRepository` composes `UniverseRepositoryMixin` and `IndexQuoteRepositoryMixin`, leaving bar/history/indicator/coverage methods and the legacy schema migration in `repository.py`. Static audit parses 120 Python files including `run.py`, with zero syntax errors and direct cross-domain imports, and observes all 40 declared transition entries. The target-specific table split between market history and reference data remains; tests were not run.

Extracted bar writes/reads, market-session queries, history revision management, quality events, indicator snapshots, and fetch coverage into `src/domains/market_data/history_repository.py`; token assignment/history readers moved into the universe concern. `MarketRepository` now composes three repository concerns while retaining schema migration and corporate-action state methods. The current AST audit below supersedes the intermediate file count recorded at this step. Tests have not been rerun after these repository extractions; the last full-suite result recorded above predates them.

## Full-suite checkpoint before market repository extraction — 2026-10-03

- Current full unit and integration run: `.venv\Scripts\python.exe -m pytest tests integration_tests -q -p no:cacheprovider --basetemp=.pytest-restructure-final2` — **453 passed in 99.95s**.
- The recursive architecture audit identified private strategy imports and a malformed import in the newly added positional-trend workflow. Those were corrected. The architecture suite passes (4 tests), and positional-trend contract/integration tests pass (17 tests).
- The source inventory was regenerated from the current 116 Python modules, including both `src/gates/workflows` modules.
- Phases 1–5 remain in progress and Phase 6 has not started; this is not a completion report.

## Current static audit after market repository extraction — 2026-10-03

- The source inventory now includes 122 Python modules under `src/`.
- AST parsing covers 123 Python files including `run.py`, with zero syntax errors.
- Static domain import analysis finds no direct cross-domain imports in `src/domains`.
- All 40 declared, exact gate transition entries correspond to observed gate imports; none are stale.
- The 453-test result above predates the market repository moves. No tests have been run since extracting the market-data repository concerns.

Strategy-definition persistence now lives in `src/domains/strategies/definitions.py`. The domain receives an injected `StrategyDefinitionValidator`; `src/gates/strategy_validation.py` adapts the indicator API and custom implementation registry. The old gate module remains a compatibility composition facade. Focused strategy, Strategy 4, account, and recursive architecture tests passed (16); focused Ruff checks passed.

Strategy-definition relocation verification: `.venv\Scripts\python.exe -m pytest tests integration_tests -q -p no:cacheprovider --basetemp=.pytest-strategy-definitions-full` — **453 passed in 102.41s**. Focused Ruff checks passed for `src/domains/strategies/definitions.py`, its public API, and the gate validation adapter. The source inventory has 122 rows matching 122 current Python modules.

### Step 56 — reference-data repository ownership and gate composition

- Moved `TrackedInstrument`, instrument/token persistence, dated reference snapshots, and token lookups into `src/domains/reference_data/repository.py`; exported the repository and contract from the reference-data package.
- Moved active-universe membership, exit eligibility, corporate-action event state and watermark persistence into `src/domains/reference_data/repository.py`; deleted the mixed market-data universe concern.
- Moved the cross-table observed-session resolution join and atomic event/market-bar adjustments into the gate aggregate. `MarketRepository` composes only the public market and reference domain exports. Application, HTTP, execution, test, and tool callers use the aggregate; the `src/application/market_repository.py` facade forwards to it. The domain migration version and SQL remain unchanged.
- Static AST parsing covered 124 Python files including `run.py`, with zero syntax errors and zero direct cross-domain imports. The recursive architecture scan reports zero violations and matched all 40 exact legacy transition entries. Smoke checks covered instrument, active-universe, bar, corporate-event, transition, and watermark persistence.
- No tests were run after this ownership split. Existing 453-test result predates market repository extraction.

### Step 57 — reference owner migration and market/reference gate seams

- Added `src/domains/reference_data/schema.py` with the `reference_data` migration namespace (versions 1–2) for instrument/token identity, universe, exit eligibility, and corporate-action event/watermark tables. `ReferenceDataRepository` initializes its own schema; its migration is additive/idempotent over the legacy namespace. Changed legacy market version 11's `series` addition to the existing idempotent column helper so reference-first initialization remains safe.
- Moved market/reference composite coverage, history, and session readers plus the observed-session calendar into gates. Bar writes receive equity/index classification from the reference repository through the gate adapter. Quality-event instrument validation now uses the table FK and maps the constraint failure to the existing domain validation error.
- Moved atomic corporate-action/market-bar transaction methods into `src/gates/repositories.py`. Market-data runtime modules no longer query reference-owned tables; their historical migration definition remains the next ownership task.
- Static AST parsing covered 125 Python files including `run.py`; recursive architecture analysis found zero boundary violations and all 40 transition imports current. Smoke checks covered both reference/legacy migration orders, composite reads, quality validation, and corporate-action adjustment. No pytest run was performed after these changes; the 453-test checkpoint predates repository extraction.
- Added `tests/reference_data/test_repository_migrations.py` to preserve owner initialization and legacy migration-order behavior. Ruff and AST checks pass; pytest was not run.

### Step 58 — market-data owner schema migration

- Added `src/domains/market_data/schema.py` with the `market_data` namespace/version 1 for market bars, current/historical index quotes, indicators, history revisions, quality events, and fetch coverage.
- Fresh repositories initialize using only `reference_data` and `market_data` owner migrations; they do not create the legacy `market` namespace. If the database already has a `market` migration record, the 17-version bridge upgrades it before both owner migrations run.
- Moved the historical mixed chain to `src/domains/market_data/legacy_schema.py` and exposed its immutable mapping for upgrade fixtures. Added `tests/market_data/test_repository_migrations.py` and extended the reference migration test with a legacy-v10-to-v17 upgrade case.
- Manual smoke checks passed for fresh owner-only initialization and legacy upgrade order, retaining reference data and final coverage columns. AST parsing passed for 129 Python files, boundary audit found zero violations and all 40 transitions current, and focused Ruff passed. Pytest was not run. Removing duplicate DDL from the upgrade bridge remains outstanding.

### Step 59 — corporate-action gate workflow

- Relocated cross-domain corporate-action orchestration to `src/gates/workflows/corporate_actions.py`; retained `src/application/corporate_actions.py` as a compatibility re-export of `CorporateActions` and `ANOMALY_THRESHOLD_PERCENT`.
- Updated composition, the market HTTP adapter, and backtest coordination to import the gate workflow. The workflow depends on a small ledger protocol, avoiding an eager import of the execution package. Moved its behavioral suite to `tests/gates/test_corporate_actions.py` and updated integration/regression test imports.
- Removed two gate-to-application corporate-action transitions. Recursive architecture audit has zero violations and observes all 38 declared transition entries. Focused Ruff passes. Pytest was not run.

### Step 60 — liquidity-universe gate workflow

- Moved JSON payload validation, domain model construction, and artifact publication from `src/application/liquidity.py` into `src/gates/workflows/liquidity_universe.py`. The reference-data domain continues to own liquidity policy and snapshot calculations; the application module is now a compatibility re-export.
- Updated gate composition to use the gate workflow and removed its exact `src.application.liquidity` transition. The integration job contract remains at `integration_tests/gates/test_liquidity_universe_job.py`.
- Recursive import-boundary audit reports zero violations and matches all 37 remaining transitions. Focused Ruff and AST checks pass; pytest was not run.

### Step 61 — retire unused application compatibility shims

- Removed `src/application/corporate_actions.py`, `exchange_calendar.py`, `nse_client.py`, and `positional_trend_jobs.py` after recursive source, test, integration, and tool searches found no remaining imports.
- Kept the implementations at their existing gate/reference-data owners and retained required compatibility imports elsewhere. Updated the removed-path inventory; current source and migration rows now track only extant modules.
- Focused Ruff and AST checks pass. Pytest was not run.

### Step 62 — universe snapshot gate workflow

- Moved `UniverseJobs` from `src/application/universe_jobs.py` to `src/gates/workflows/universe.py`. It sequences reference-owned NSE/provider data and persistence with market-session evidence and exit-eligibility recording through the public gate repository.
- Updated composition and all source/test imports, moved its focused test to `tests/gates/test_universe_jobs.py`, removed the exact composition transition, and retired the old application file after a caller audit.
- Focused Ruff passes. The following Step 63 audit covers the resulting combined tree; pytest was not run.

### Step 63 — portfolio sync gate workflow

- Moved `PortfolioSync` into `src/gates/workflows/portfolio_sync.py` and redirected composition, the integration suite, and the phase-repair tool. Removed the old application implementation after confirming no remaining imports.
- Moved retained strategy IDs into the public strategies API and changed execution-account code to consume that domain contract. The gate workflow now depends on account, ledger, and instrument-reader protocols instead of importing concrete execution adapters.
- Recursive boundary audit reports zero violations with all 35 current transitions observed. AST parsing passes for 128 Python files, and source/test inventory coverage matches all 124 source and 91 test/integration modules. Focused Ruff passes; pytest was not run.

### Step 64 — market refresh gate workflow

- Moved `MarketRefreshPlanner` into `src/gates/workflows/market_refresh.py`; composition, market HTTP, pipeline preparation integration, refresh integration, and behavioral fixtures now import that path.
- Removed the two exact gate-to-application transitions and deleted the application implementation after a caller audit. Market session/coverage reads remain in their domains and gate adapters.
- Recursive boundary audit reports zero violations with all 33 current transitions observed. AST parsing passes for 130 source/entry/affected-test files, and inventory coverage matches all 124 source and 91 test/integration modules. Focused Ruff passes; pytest was not run.

### Step 65 — pipeline preparation workflow and market index contract

- Moved the sequential manual prerequisite coordinator into `src/gates/workflows/pipeline_preparation.py`; composition and its integration workflow use the gate path, and the old application implementation was removed after a caller audit.
- Defined `NSE_INDEX_SYMBOLS` in the market-data public API and made both the refresh and preparation workflows consume it. The application market-jobs module retains `PHASE2_BENCHMARK_SYMBOLS` as a compatibility alias.
- Recursive boundary audit reports zero violations with all 32 current transitions observed. AST parsing passes for 222 source, test, integration, tool, and entry files; exact manifest coverage matches all 124 source and 91 test/integration modules. Focused Ruff and workflow import smoke pass; pytest was not run.

### Step 66 — index-poller gate lifecycle

- Moved `IndexQuotePoller`, `BackgroundIndexPoller`, and market-session polling checks into `src/gates/workflows/index_poller.py`. App startup, CLI, composition, HTTP, and integration callers use the gate path; the old application source was removed after a caller audit.
- Kept the `index_poller` migration namespace and versions unchanged while assigning ownership of its durable scheduler state to gates.
- Recursive boundary audit reports zero violations with all 28 current transitions observed. AST parsing passes for 222 source, test, integration, tool, and entry files; exact inventory coverage matches all 124 source and 91 test/integration modules. Focused Ruff and workflow import smoke pass; pytest was not run.

### Step 67 — intraday stream gate lifecycle

- Moved `IntradayStreamLease` into `src/gates/workflows/intraday_stream.py`; CLI, composition, HTTP, and regression/integration callers now use the gate path. Removed the old application module after a caller audit.
- Kept the `intraday_stream` migration namespace, versions, and lease table unchanged while assigning its durable lifecycle state to gates.
- Recursive boundary audit reports zero violations with all 25 current transitions observed. AST parsing passes for 222 source, test, integration, tool, and entry files; exact inventory coverage matches all 124 source and 91 test/integration modules. Focused Ruff and workflow import smoke pass; pytest was not run.

### Step 68 — live quote and stop-alert domain ownership

- Moved quote validation, persistence, account isolation, and freshness classification to `src/domains/market_data/live_quotes.py` and exported `LiveQuotes` from the market-data API. Existing `live_quotes` schema namespace/version/table are preserved.
- Moved stop-alert eligibility, idempotent identity generation, persistence, and readback to `src/domains/portfolio_accounting/intraday_alerts.py`. The domain consumes ledger, risk-projection, and artifact-publication ports; composition supplies concrete implementations.
- Moved `LiveQuoteStream` into `src/gates/workflows/live_quote_stream.py`; updated composition, HTTP typing, and callers. The Kite streaming adapter remains in `src/application/providers.py`; composition injects it through one exact tracked transitional import pending provider ownership migration.
- Split alert verification into `tests/portfolio_accounting/test_intraday_alerts.py` and `integration_tests/gates/test_intraday_alerts.py`; moved stream lease HTTP lifecycle coverage under gate integration tests.
- Removed the unused `src/application/intraday_alerts.py` and `src/application/live_quotes.py` shims after a full source/test/integration/tool caller audit. Alert unit coverage now lives under `tests/portfolio_accounting`; HTTP and lease lifecycle coverage live under `integration_tests/gates`.
- AST inventory lists 125 source modules. AST parsing passed for 224 source, test, integration, tool, and entry files. Recursive boundary analysis reports zero violations with all 23 exact transitions observed; focused Ruff and workflow/composition import smoke pass. Pytest was not run.

### Step 69 — market provider adapters

- Moved `KiteHistoricalBarsProvider`, `KiteInstrumentProvider`, `KiteQuoteProvider`, and their rate limiter into `src/domains/market_data/providers.py`; exported them through the market-data API and redirected market jobs, adapter tests, and throttle stubs.
- Kept `KiteStreamingProvider` in `src/application/providers.py`; this remaining account-scoped adapter is still used by gates composition through the exact tracked transitional import.
- AST inventory at Step 71 listed 126 source modules. Syntax parsing passed for 225 source, test, integration, tool, and entry files; all 126 source modules and 92 test/integration modules were present in the manifest. Recursive boundary analysis reported zero violations with 23/23 exact transitions observed, and focused Ruff passed. Pytest was not run.

### Step 70 — market job and ingestion workflows

- Moved `KiteMarketJobs` and `ingest_market_bars` to `src/gates/workflows/market_jobs.py` and `src/gates/workflows/market_ingestion.py`. Composition binds market job methods directly as durable handlers; gate workflows coordinate provider reads, artifact publication, market persistence, coverage, and stop-alert polling.
- Updated every production/test/tool caller, moved the ingestion integration test to `integration_tests/gates`, and removed `src/application/market_jobs.py`, `src/application/ingestion.py`, and the exact composition-to-application job transition. The NSE index contract remains owned by `domains/market_data`.
- Composition handler-binding and raw-to-normalized lineage smoke checks pass. Syntax parsing covers 223 files. Recursive boundary analysis reports zero violations with 22/22 exact transitions observed; focused Ruff and source/test manifest coverage pass. Pytest was not run.

### Step 71 — retire unused artifact facades

- Removed the unused five-line `src/application/catalog.py` and `src/application/publication.py` compatibility facades after recursive source, test, integration, tool, and entry-point searches found no remaining callers. Public callers already use `src.domains.artifacts`; catalog and publication behavior is unchanged.
- Regenerated the current AST inventory for 124 source modules. Source/test manifests match 124 source and 92 test/integration files; syntax parsing covers 223 source, test, integration, tool, and entry files. Recursive boundary analysis still reports zero violations and 22/22 exact transitions; focused Ruff passes. Pytest was not run.

### Step 72 — execution authentication ownership

- Moved Kite credential loading, login URL/session exchange, and atomic token-file replacement from `src/application/kite_auth.py` into `src/domains/execution/kite_auth.py`; added a curated execution API and package export.
- Updated app lifecycle, CLI, composition, HTTP auth, execution adapter, and tests to use `src.domains.execution`. Removed the four exact gate-to-application Kite-auth transition entries. Token formats, credential profile names, and login behavior are unchanged.
- Credential-profile checks and a fake-client login/token persistence smoke pass; AST parsing covers 225 files and exact manifests cover 126 source plus 92 test/integration files. Recursive boundary analysis reports zero violations with all 18/18 exact transitions observed. Focused Ruff and gate/domain import smoke pass. Pytest was not run.

### Step 73 — remove unused application re-exports

- Removed `src/application/jobs.py`, `worker.py`, `security.py`, `positional_trend.py`, and `cli.py` after repository-wide production, test, integration, tool, and entry-point searches found no imports through those module paths. Implementations remain under operations, platform kernel, strategies, or gates.
- Kept `src.application` package-level `JobStore`/`JobWorker` exports domain-backed for existing callers, and kept the stable `run.py` entry point. The obsolete `application.cli` subpath is not a configured console entry point.
- Regenerated the AST inventory and rechecked exact manifests (120 source, 92 test/integration), syntax across 219 Python files, zero recursive boundary violations with 18/18 transitions, focused Ruff, and domain/package import smoke. Pytest was not run.

### Step 74 — remove market repository re-export

- Removed the unused five-line `src/application/market_repository.py` wrapper after checking all source, test, integration, tool, and entry-point references. The composite gate repository remains in `src/gates/repositories.py`; table persistence remains split into domain-owned repositories.
- The architecture regression continues to reject the retired application import path. Behavior and schema ownership are unchanged.
- AST parsing covers 219 files; exact manifest coverage matches 120 source and 92 test/integration modules. Recursive boundaries report zero violations and 18/18 transitions; focused Ruff and package import smoke pass. Pytest was not run.

### Step 75 — portfolio proposal persistence ownership

- Added `domains/portfolio_engine/proposal_store.py` and moved the `actions` migration, proposal projection writes/recovery, lifecycle reads, account/date queries, event appends, and pending-to-approved/rejected transitions out of `ActionJobs`. The existing migration namespace/version and table definitions are retained.
- Kept cross-domain request validation, artifact recovery reads, risk checks, and ledger coordination in the legacy coordinator for the next gate workflow migration. Processing now passes its existing `BEGIN IMMEDIATE` transaction connection to the portfolio store for proposal status/event writes, preserving the no-fill ledger-version check and atomic proposal update.
- Added focused store lifecycle/idempotency tests. A manual repository smoke passed migration, idempotent recovery, account/date reads, pending-to-approved transition, and processed-event persistence. AST parsing covers 221 files; exact manifests match 121 source and 93 test/integration modules; recursive boundaries report zero violations with 18/18 transitions; focused Ruff passes. Pytest was not run.

### Step 76 — move portfolio action coordination to gates

- Moved `ActionJobs` from application into `gates/workflows/portfolio_actions.py`; composition and HTTP adapters plus regressions now import the gate path. The workflow delegates proposals, events, and status transitions to the portfolio-engine store.
- Moved canonical/legacy strategy identifier mapping to `domains/strategies/identity.py` and exposed `resolve_strategy_id`, `feature_series`, and `valid_bar` through the curated strategies package API. The old strategy runtime re-exports identifier names for its remaining callers.
- Removed the two composition/HTTP action-service transitions and declared the workflow’s remaining research-service and legacy ledger imports as two exact transitions. Gate workflow/store and strategy API smoke pass; exact manifests match 122 source and 93 test/integration modules, AST parsing covers 222 files, recursive boundaries report zero violations with 18/18 transitions, and focused Ruff passes. Pytest was not run.

### Step 77 — backtest run persistence ownership

- Added `domains/backtesting` with a curated API and `BacktestRunStore`; moved the existing version-1 `backtest` migration and run-index insert/list/artifact lookup/delete operations out of `BacktestJobs`. Normal inserts still reject duplicate run IDs; Strategy 4 replay remains `INSERT OR IGNORE`.
- `BacktestJobs` now delegates persisted run operations to the domain store. Replay calculation, artifact publication, catalog checks, market/research assembly, and Strategy 4 input work remain in the application coordinator for a later gate/domain split.
- Added store regression tests. A manual smoke passed fresh schema initialization, duplicate rejection versus insert-if-missing, run listing/artifact lookup/deletion, and BacktestJobs delegation. Exact manifests match 125 source and 94 test/integration modules; AST parsing covers 226 files; recursive boundaries report zero violations with 18/18 transitions; focused Ruff and import smoke pass. Pytest was not run.

### Step 78 — consolidate backtesting engine under its domain

- Moved the framework-free replay/result implementation from `src/backtesting/api.py` to `src/domains/backtesting/simulation.py`. Consolidated its curated exports with `BacktestRunStore` under the backtesting domain API and updated every internal source/test/tool caller.
- Removed the old `src/backtesting` package after the caller audit. Updated `BacktestJobs` content-fingerprint inputs to hash the new authoritative simulation module path. The engine depends only on its own contracts and the kernel; a gate adapter injects portfolio evaluation and its concrete value types.
- The replay now receives a `PortfolioEnginePort`; no backtesting-domain module imports portfolio-engine modules. All 18 exact transitions remain current, the recursive boundary scan reports zero violations, and a portfolio-adapter replay smoke passes. Pytest was not run.


### Step 79 — move backtesting workflow coordination to gates

- Moved `BacktestJobs` to `src/gates/workflows/backtesting.py`; composition and the backtest HTTP adapter now depend on the gate workflow. The workflow continues to use the public backtesting API/store and domain-owned market history reader.
- Replaced the composition and HTTP exceptions for the old application coordinator with exact allowlist entries for the gate workflow’s remaining `ResearchJobs` and Strategy 4 input-loader imports. Updated both content-revision hashes to track the relocated workflow and the actual Strategy 4 policy/loader sources.
- Added `MarketHistoryRepositoryMixin.history_snapshot_rows` as a market-owned batched reader used by the workflow. No table ownership or SQL schema changed.
- Verification: the refreshed AST inventory exactly matches 125 source modules; 94 test/integration modules are present; all source files parse; the recursive boundary scan has zero violations and observes 18/18 exact transitions. Focused Ruff lint and formatter checks pass for the moved backtesting code, the revision hash resolves, and a disposable SQLite smoke passes gate composition import, empty run-store delegation, and deterministic sorted/deduplicated market-history identity reads. Pytest was not run.


### Step 80 — separate Strategy 4 policy/replay from input adapters

- Moved `Policy`, equity-at-open valuation, and the full next-open Strategy 4 replay into `src/domains/strategies/positional_trend_backtest.py`. The strategy implementation depends only on the strategies domain and standard-library calculation modules; the public strategies API now exports its policy and replay.
- Moved CSV membership, market-cap/snapshot history assembly, and benchmark reads into `src/gates/workflows/positional_trend_backtest_inputs.py`, then deleted the former mixed application module. Updated the production backtest workflow, CLI tools, and regression callers.
- Updated replay fingerprints to include the domain simulation and gate input-adapter source. The old application seam is removed; recursive boundaries report zero violations with 17/17 exact transitions. A deterministic next-open/fees fixture passes; focused Ruff and AST checks pass. Pytest was not run.


### Step 81 — move strategy runtime composition to gates

- Moved `StrategyRuntime` out of the legacy application package into `src/gates/strategy_runtime.py`. It coordinates strategy definitions, indicator DAG execution, and the gate-owned implementation registry, so it stays at the interaction layer.
- Switched its indicator dependency to the curated `src.domains.indicators` API. Updated composition, research/pipeline consumers, payload identity lookups, integration callers, and the focused test location. The composition-to-application runtime exception was retired.
- Verification: 126 source files parse; source and migration inventories are refreshed; the recursive boundary scan reports zero violations and observes all 16/16 exact transitions. Focused Ruff passes and all 15 StrategyRuntime regression functions pass when called directly. Pytest was not run.


### Step 82 — establish research persistence ownership

- Added `src/domains/research/ResearchRepository` as the owner for the existing `research` SQLite namespace. Migration versions 1–3 and all five table definitions remain unchanged.
- Moved daily-score replacement/upsert, weekly-ranking writes and reads, percentile snapshot persistence, and immutable lineage operations into the repository. `ResearchJobs` retains calculation, validation, artifact publication, and workflow behavior while delegating every research-table read/write.
- Moved persistence regressions under `tests/domains/research`. Direct execution passes all 7 repository regression functions and both bulk-rebuild workflow regression functions. Source and current-source manifests refresh to 129 exact modules; recursive boundaries remain at zero violations with 16/16 exact transitions; focused Ruff passes. Pytest was not run.

### Step 83 — move reusable research calculations into the domain

- Added pure calculation contracts in `src/domains/research/calculations.py` and exported them through the curated research API. Sector factor normalization, Pearson correlation/clusters, return-anomaly scoring, and weekly ranking aggregation now belong to the research domain; `ResearchJobs` retains input loading, parameter validation, artifact publication, and coordination.
- Preserved runtime-owned factor weights, absolute correlation threshold behavior, deterministic cluster ordering, anomaly bar lineage, and weekly score/symbol tie policy. Added four direct domain regression functions and reran four existing sector/anomaly workflow functions successfully without pytest.
- Exact AST inventory and current-source manifest match all 130 Python source modules; the test/integration manifest exactly matches all 95 modules. Focused Ruff lint passes; the new domain calculation module, API and test are formatter-clean. All four recursive architecture-boundary regressions pass with zero violations and 16/16 exact transitions; all 130 sources parse. Pytest was not run.

### Step 84 — move research orchestration into gates

- Moved `ResearchJobs` to `src/gates/workflows/research.py` and its workflow payload parsers to `src/gates/payloads.py`. Composition, research HTTP, backtesting, portfolio actions, integrations, and regression imports now use the gate paths; the old application modules were removed.
- Switched the gate workflow to public indicator, strategy, and research APIs; corrected the strategy seed and indicator-code paths for the deeper module location. The workflow hashes its own source in the indicator implementation revision, so relocation intentionally invalidates cached node outputs and causes a rebuild with unchanged cache semantics.
- Retired the composition, backtest, portfolio-action, and research HTTP legacy research-service exceptions. The recursive audit passes with zero violations and 12/12 exact transitions. Direct execution passes 39 targeted research, composition, backtesting, portfolio lifecycle, and pipeline-preparation regressions; focused Ruff lint and formatter checks pass. The 130-source and 95-test/integration manifests are exact. Pytest was not run.


### Step 85 — move research pipeline persistence and coordination

- Added `src/domains/research/pipeline_repository.py` for `research_pipelines` and `research_pipeline_stages`. The existing `research_pipeline` migration namespace and versions 1–3 are unchanged; the gate no longer owns those tables or SQL.
- Moved `ResearchPipelineJobs` into `src/gates/workflows/research_pipeline.py`; composition, CLI, HTTP, tests, and parity callers now import its gate path. It delegates persistence to the research domain while preserving stage order, idempotent stage inserts, deferred advances, retries, cancellation, and job type strings.
- Added direct repository coverage for pipeline/stage writes, stage-pointer updates, idempotent insertion, missing reads, and migration ledger versions. A post-move direct pass of 32 repository, workflow, parity, composition, action-lifecycle, and boundary regressions passes; the pipeline CLI status/readback regression also passes. Recursive boundaries remain clean with 9 exact transitions. The 131-source and 96-test/integration manifests match the worktree. Pytest was not run.


### Step 86 — move portfolio reservations into their owner

- Moved `ManagedRiskGuard` from application into `gates/workflows/managed_risk.py`; composition and its integration coverage now use the gate path. It remains a gate because it coordinates ledger, market prices, sector evidence, portfolio limits, and the risk reader under one immediate transaction.
- Added `domains/portfolio_engine/risk_reservations.py` and its public `RiskReservationRepository` contract for the unchanged `risk_reservations` version-1 schema. Reads, writes, and release accept the caller’s SQLite connection, preserving the transaction shared with ledger-version checks and configuration reads.
- Added rollback/upsert/release/ledger-version repository regressions. Direct execution passes 2 repository, 4 existing managed-risk integration, 4 architecture, 1 composition, and 12 action-lifecycle regressions. Focused Ruff lint/format and recursive boundaries pass with 8 exact transitions. Pytest was not run.


### Step 87 — move execution stream adapter and remove dead facades

- Moved KiteStreamingProvider from src/application/providers.py to src/domains/execution/streaming_provider.py, exposed it from the curated execution API, and updated composition plus provider/live-stream tests.
- Removed the obsolete src/application/runs.py helper and src/application/liquidity.py re-export after repository-wide source, test, integration-test, tools, and entry-point searches found no consumers. Kept only still-used artifact and operations exports in src/application/__init__.py.
- Ran 11 direct provider, live-stream integration, and architecture-boundary regressions; all passed. Ruff checks/formatting passed for moved code and call sites.


### Step 88 — move portfolio risk configuration into its owner

- Moved `RiskGuardLimits` and `PortfolioRiskConfig` from the legacy execution gateway to `src/domains/portfolio_engine/risk_config.py`, exposed them through the portfolio-engine public API, and updated composition, the portfolio HTTP adapter, integration tests, and verification tool.
- Preserved the `portfolio_risk_config` schema namespace/version 1 and all request/response configuration fields. Removed the legacy module and its two exact transition exemptions.
- Ten direct configuration, managed-risk, composition, and architecture regressions passed; focused Ruff checks passed.

### Step 89 — move broker accounts into execution

- Moved `KiteAccounts` to `src/domains/execution/accounts.py` and exported it from the execution API. Composition, integration tests, and the verification tool use the domain-owned contract.
- Preserved `kite_accounts` versions 1–2 and existing session/account behavior. Strategy IDs now enter through an allowed-ID constructor contract, avoiding a direct execution-to-strategies import; the compatibility default retains the current supported IDs.
- Removed the old implementation and retired the composition transition. Seven direct account, portfolio-sync, composition, and boundary regressions passed; focused Ruff checks passed.


### Step 90 — extract the broker provider adapter

- Moved `BrokerExecutionGateway` and `KiteExecutionGateway` into `src/domains/execution/broker_adapter.py` and exposed them from the execution API. Composition and adapter tests use the new public API; legacy exports remain available to the still-existing broker order coordinator.
- Kept `BrokerOrderService` and its `broker_orders` schema in the legacy gateway because it coordinates durable intents, idempotency, ledger fill posting, and market-membership checks. These require separate repository and injected-port work before relocating the service.
- Eleven direct broker adapter/lifecycle, composition, and architecture regressions passed. Focused Ruff lint and formatting passed.


### Step 91 — move append-only ledger into portfolio accounting

- Moved the `Ledger` implementation to `src/domains/portfolio_accounting/ledger.py` and exported it from the portfolio-accounting public API. Composition, gate workflows, HTTP adapters, broker reconciliation, tests, and tools now consume the owner API. The legacy execution package keeps a package-level `Ledger` re-export while callers migrate; its old ledger module is removed.
- Preserved the ledger schema namespace and versions 1–4, event payload shapes, idempotency keys, caller-owned fill transaction semantics, valuation snapshots, and opening-position import/replay behavior.
- Removed gate-to-legacy-ledger allowlist entries. Twenty-eight direct ledger and dependent-workflow/composition/boundary regressions passed; focused Ruff passed.
- `BrokerOrderService` remains in the legacy execution package. Its intent tables and reconciliation still coordinate ledger writes, risk checks, and market membership, so extract its order-state persistence and membership port before moving the coordinator.


### Step 92 — retire the empty application package

- Repository-wide searches across source, tests, integration tests, tools, `run.py`, `pyproject.toml`, and the Makefile found no remaining imports of the package exports. Removed `src/application/__init__.py` and the empty package directory. The architecture checker continues to reject any future domain dependency on `src.application`.
- Current source and AST inventories now contain 130 modules; the test/integration inventory remains at 97. Recursive boundary checks continue to enforce the retired package root.


### Step 93 — retire legacy indicator and strategy facades

- Repository-wide source, tests, integration tests, tools, entry points, and package-script searches found no imports of `src.indicators` or `src.strategies`. Removed the legacy package initializers and `src/strategies/api.py`; callers already use the curated `src.domains.indicators` and `src.domains.strategies` APIs.
- Kept both names in the recursive boundary checker’s legacy roots so new source imports are rejected. Current source inventory now contains 127 modules; the test/integration inventory at this step contained 97. It now contains 98 modules following Step 94’s focused repository regression.


### Step 94 — move broker order persistence and orchestration to their owners

- Added `src/domains/execution/order_repository.py` with the unchanged `broker_orders` migration namespace and versions 1–3, table schema, basket/order persistence, idempotency checks, event sequencing, and submission/reconciliation state transitions.
- Moved the cross-domain coordinator into `src/gates/workflows/broker_orders.py` as `BrokerOrderWorkflow`. It consumes the execution repository, public portfolio proposal/ledger APIs, execution account/gateway APIs, the gate market repository, and the managed risk guard. It no longer performs SQL or constructs a market repository internally when composed.
- Updated composition, broker HTTP, tests, and the verification tool. Removed the final `src/execution_gateway` package and retired its two exact transitional imports. The architecture checker keeps that package name reserved as a forbidden legacy dependency.
- Twenty-six direct broker repository/workflow, execution-owner, portfolio, HTTP, composition, and boundary regressions pass. Focused Ruff checks pass.
