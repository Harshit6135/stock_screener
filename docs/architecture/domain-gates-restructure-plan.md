# Domain and gates restructuring plan

Prepared 2026-10-03. Detailed Luna handoff for final verification of the domain/gates restructure. Implementation Steps 1–94 are present in this worktree; use the migration manifest and current-source inventory as the source of truth for status.

## Clean implementation policy

This policy supersedes compatibility language elsewhere in this plan and in the historical migration log. The app is in active development: do not preserve old strategy names, routes, job types, files, database migration chains, schemas, stored rows, or artifact identities. Start from the current canonical contracts and a fresh database. Keep consistency within the current implementation, but add no adapters or upgrade behavior for previous edits.

## 1. Objective and decisions

Make every business capability discoverable in one domain, with gates providing the interactions between domains and the application entry points. Keep the existing modular monolith, Flask/Waitress runtime, durable jobs, and SQLite database.

The target has three responsibilities:

1. `src/domains/<domain>/`: the complete capability, including contracts, rules, services, repositories, migrations, and capability-specific provider adapters.
2. `src/gates/`: HTTP/CLI adapters, cross-domain workflows, dependency wiring, and process lifecycle.
3. `run.py`: stable public entry point delegating application construction and server startup to gates.

Keep `src/platform_kernel/` as the small shared foundation. It is an explicit exception to the two main folders, not another place for application features. Do not rename the `src` package during this restructuring.

Prefer fewer coherent modules over many tiny files. Do not create mandatory `models/services/repositories/adapters` subfolders in every domain. Start with sibling modules; create a subgroup only when an existing capability contains several related implementations. Do not merge unrelated code just to reduce file count.

Domain standalone means it can be constructed and exercised with injected contracts and test adapters, without Flask, gates, `run.py`, or another domain's implementation. It does not require a separate service, database, or process.

## 2. Findings from the current repository

- Domain capabilities are consolidated under `src/domains`; gates coordinate domain interactions.
- `src/application` mixed single-domain calculations, repositories, provider integrations, orchestration, route adapters, and process setup; the package was retired in Step 92 after caller audits.
- `src/gates/strategy_definitions.py` adapts strategies-owned persistence and validation. `src/gates/session_coverage.py` coordinates market/reference reads; audit direct SQL and retain only explicitly documented cross-domain atomic operations.
- `run.py` delegates application creation and startup to `src.gates.app`, preserving `create_app` and `main`; route registration and composition live in gates.
- `tools/verify_import_boundaries.py` recursively enforces domain, gate, kernel and legacy-root boundaries, including relative and literal dynamic imports; it is a repository check rather than a test for one source module.
- `docs/architecture/domain-module-inventory.md`, `docs/src-file-inventory.md`, and the migration manifest record current owners and migration history. Reconcile discrepancies against the source tree rather than repeating completed moves.
- The unified test tree mirrors `src/` by relative directory and source-module basename: each tested `src/.../name.py` has one `tests/.../test_name.py`. Keep each file focused on the behavior of its matching source module, including gate-owned cross-domain interactions. Do not create a separate integration-test subtree.
- Path-sensitive code exists in composition, pipeline/research jobs, positional-trend jobs, backtest jobs, dashboard templates, and wiki loading. Code hashes also read hard-coded source filenames.
- Root `db.py` references Flask-SQLAlchemy, while the current application uses SQLite stores. Root `test.py` references obsolete `run.app` and `src.services.percentile_service`. Determine their remaining callers before retiring them.
- Existing repair-status documents include outstanding functional work. Record pre-existing failures separately; restructuring is not permission to silently fix strategy or trading behavior.

## 3. Target layout

```text
run.py
src/
  platform_kernel/
    api.py, contracts.py, ports.py, errors.py
    sqlite.py, artifacts.py, security.py
  domains/
    reference_data/
      api.py, services.py, instruments_repository.py
      universe_repository.py, corporate_actions_repository.py
      calendar.py, nse_provider.py, liquidity.py
    market_data/
      api.py, services.py, repository.py, providers.py
      ingestion.py, quotes.py, stream_state.py, quality.py
    indicators/
      api.py, registry.py, dag.py, node_cache.py
      relative_strength.py, momentum_quality.py, custom/
    strategies/
      api.py, definitions.py, repository.py, runtime.py
      ranking_patterns.py, momentum_quality.py, positional_trend.py
      presets/
    research/
      api.py, services.py, repository.py
    backtesting/
      api.py, services.py, repository.py, positional_trend.py
    portfolio_engine/
      api.py, services.py, risk.py, proposals_repository.py
    portfolio_accounting/
      api.py, ledger.py, portfolio_performance.py
    execution/
      api.py, broker.py, accounts.py, auth.py, providers.py
      risk_config.py
    operations/
      api.py, jobs.py, worker.py, release_checks.py
    artifacts/
      api.py, catalog.py, publication.py
  gates/
    app.py, composition.py, runtime.py, lifecycle.py, cli.py
    http/
      dashboard.py, wiki.py, health.py, operations.py
      reference.py, universe.py, market.py, research.py
      pipeline.py, indicators.py, strategies.py, portfolio.py
      broker.py, accounts.py, auth.py, backtest.py, actions.py
      positional_trend.py
    workflows/
      market_refresh.py, market_ingestion.py, session_coverage.py
      research.py, pipeline.py, portfolio_actions.py
      portfolio_sync.py, corporate_actions.py, backtesting.py
      live_market.py, managed_risk.py
    jobs/
      registry.py, market.py, universe.py, research.py
      pipeline.py, actions.py, backtesting.py, positional_trend.py
templates/
static/
tests/
  domains/<domain>/      # test_<src module>.py
  gates/http/            # test_<src module>.py
  gates/workflows/       # test_<src module>.py
  gates/                 # test_<src module>.py
  platform_kernel/       # test_<src module>.py
tools/
docs/
```

This tree describes responsibility destinations, not a requirement to create each listed file. Reuse a cohesive existing module where splitting would add no value. Keep root templates/static initially because moving Python and browser assets together makes regressions harder to isolate. Route-specific frontend grouping is an optional later task.

## 4. Domain ownership

| Domain | Owns | Does not own |
| --- | --- | --- |
| reference_data | Instrument identity/aliases, dated universe membership, exchange calendar, corporate-action reference events, liquidity eligibility | OHLCV history, account fills, scheduling research |
| market_data | Normalized bars, history revisions, quality events, market/index quotes, provider fetch/normalization and stream state | Universe membership policy, strategy scoring, portfolio stop decisions |
| indicators | Registry, DAG validation/execution, calculations, node cache and cache identity | Strategy definitions, portfolio policy, pipeline execution |
| strategies | Immutable definitions/revisions, preset loading, strategy IDs/aliases, ranking and signal decisions | Fetching history, indicator implementation internals, brokerage |
| research | Persisted research projections/results, research-specific calculations, result queries and rebuild identity | Direct reads of market/strategy/indicator tables, HTTP, worker scheduling |
| backtesting | Simulation/replay, stress/walk-forward/attribution, backtest run records | Live orders, ledger writes, direct market/reference SQL |
| portfolio_engine | Proposal lifecycle/state, allocation and exit policy, risk policy and projections, intraday stop evaluation | Broker submissions, accounting source-of-truth, cross-domain coordination |
| portfolio_accounting | Fills/opening positions, ledger, accounting events, projections and performance | Broker credentials/orders, market fetches, approval orchestration |
| execution | Broker profiles/auth, account bindings, order intents/submission/reconciliation, provider adapters, execution risk configuration | Owning ledger rows, choosing strategies, importing market repositories |
| operations | Durable jobs/events/progress/cancellation, leases, generic worker dispatch, operational release checks | Importing feature job handlers or deciding business eligibility |
| artifacts | Artifact catalog/publication/recovery and lineage orchestration over neutral storage primitives | Calculating strategy results or owning domain projections |

Use existing domain names where possible. The separate research, operations, and artifacts domains provide clear owners for substantial existing stateful functionality. Do not invent a domain for each web page or each job.

The physical database remains `instance/stock_screener.db`. Table ownership is logical: a domain's repository is the only code allowed to query/write its tables. Schema/migration namespaces, table names, data formats, and transaction semantics remain stable.

## 5. Enforceable dependency rules

```text
run.py -> gates -> domain public APIs -> platform_kernel
               -> platform_kernel
domains -> their own modules
platform_kernel -> standard library / neutral infrastructure libraries
```

- Domains never import `src.gates`, `src.application`, `run`, or another domain implementation/public API. Under the requested strict boundary, even cross-domain public API imports are replaced with injected contracts.
- A consuming domain declares its small `Protocol` in its own `api.py` or `ports.py`. Gates construct adapters that call the providing domain's public API. Use neutral DTOs/value types where appropriate. Avoid moving every domain type into the kernel.
- Gates may import `src.domains.<name>.api` or that domain's explicitly curated package exports. They must not reach into another module to instantiate private repositories or issue SQL.
- Public APIs export construction factories and narrow services/readers; they should not export every internal helper. Keep package `__init__.py` inert or limited to curated exports; no startup/network/worker side effects.
- Domain cores stay framework-free. SQLite, requests, pandas, or broker SDK use is allowed in owned adapters/repositories, not forced into the core. A recursive blanket ban on all infrastructure dependencies would contradict a domain owning all its functionality.
- Operations workers receive a handler mapping from gates; operations must not import gates to discover jobs.
- Framework request parsing and response serialization live in HTTP gates. Job payload parsing/dispatch lives in job gates. Business validation remains in its domain.
- Gates own sequencing and adaptation. They do not own business tables, strategy formulae, or reusable portfolio calculations.
- Never route all communication through a generic service locator or global mutable registry. Constructor injection should make each workflow's dependencies visible.

Example: research gate reads a dated market/reference snapshot through public readers, asks indicators to calculate features, asks strategies to rank those features, asks research to store its projection, then publishes through artifacts. Strategies receive feature data or an injected indicator evaluator; they do not import the indicator DAG implementation.

## 6. File migration map

For mixed modules, split by symbols after a function/table audit. Do not move the entire file into a gate and declare the ownership problem solved.

| Current source | Destination / required treatment |
| --- | --- |
| `src/reference_data/*` | moved into `domains/reference_data`, preserving API symbols |
| `src/market_data/*` | moved into `domains/market_data` |
| `src/indicators/*` and existing `domains/indicators/*` | legacy facade retired; implementation consolidated in `domains/indicators` |
| `src/strategies/*` and existing `domains/strategies/*` | legacy facade retired; implementation consolidated in `domains/strategies` |
| `src/backtesting/*` | Moved into `domains/backtesting` in Step 78; the legacy package is removed, and portfolio evaluation is injected through a gates adapter |
| `src/portfolio_engine/*` | moved to `domains/portfolio_engine` |
| `src/portfolio_accounting/*` and existing performance module | consolidated in `domains/portfolio_accounting` |
| `execution_gateway/ledger.py` | moved to `domains/portfolio_accounting/ledger.py` in Step 91; execution calls the accounting API |
| `execution_gateway/broker.py` | moved in Step 94: broker tables/events to `domains/execution/order_repository.py`; cross-domain workflow to `gates/workflows/broker_orders.py` |
| `execution_gateway/kite_accounts.py` | moved to `domains/execution/accounts.py` in Step 89; supported IDs are injected by gates from the strategies API |
| `execution_gateway/risk_guard.py` | moved to `domains/portfolio_engine/risk_config.py` in Step 88; schema version and public config fields preserved |
| `gates/repositories.py`, `domains/market_data/*`, `domains/reference_data/*` | Composite queries and atomic cross-owner operations stay in gates; table access and fresh schemas belong to their domains. Only the current schema is supported. |
| `application/providers.py` | Historical/instrument/quote adapters are in `domains/market_data`; account-scoped `KiteStreamingProvider` moved to `domains/execution/streaming_provider.py` in Step 87 |
| `application/nse_client.py`, `exchange_calendar.py`, `universe_jobs.py` | Moved to reference-data providers and `gates/workflows/universe.py`; preserve provider and durable-job contracts |
| `application/ingestion.py`, `market_jobs.py` | Moved to `gates/workflows/market_ingestion.py` and `market_jobs.py`; provider adapters and normalized bar contracts remain in market_data |
| `application/market_refresh.py` | Moved to `gates/workflows/market_refresh.py`; coverage/history rules remain in owning domains |
| `gates/workflows/index_poller.py` | Current gate-owned poller lifecycle; quote semantics and persistence are exposed through market-data APIs |
| `application/live_quotes.py`, `intraday_stream.py` | Quote storage/freshness in `domains/market_data`; durable lease and broker stream lifecycle in `gates/workflows` |
| `application/intraday_alerts.py` | Fill-free stop evaluation/read model in `domains/portfolio_accounting`; observation dispatch in gate workflow |
| `gates/workflows/corporate_actions.py` | Current cross-domain workflow for reference detection, market adjustments, accounting events, publication and invalidation; pure parsing/rules remain candidates for an explicit extraction audit |
| `application/liquidity.py` | Payload parsing/publication moved to `gates/workflows/liquidity_universe.py`; liquidity calculation remains reference-data-owned |
| `gates/strategy_definitions.py` | Strategy definitions/repository under domains/strategies |
| `gates/strategy_runtime.py` | Cross-domain StrategyRuntime composes strategy definitions, indicator DAG execution, and implementation registries; moved to gates in Step 81, with identifiers owned by `domains/strategies` |
| `application/positional_trend.py` | Signal policy moved to `domains/strategies/positional_trend.py`; reusable features remain classified by their owner |
| `application/positional_trend_jobs.py` | Job/build coordination moved to gates; strategy calculations and research projections use owner APIs |
| `domains/strategies/positional_trend_backtest.py`, `gates/workflows/positional_trend_backtest_inputs.py` | Strategy 4 policy and replay moved to strategies in Step 80; CLI/composite input loaders moved to a gate adapter; migrate its SQL reads onto public owner repositories as those contracts are completed |
| `gates/workflows/research.py` | Research persistence is owned by `domains/research/repository.py`, pure calculations by `domains/research/calculations.py`, and market/runtime/artifact/job coordination by this gate workflow (Step 84) |
| `gates/workflows/backtesting.py` | BacktestJobs gate workflow moved in Step 79; `backtest_runs` persistence and replay engine are owned by `domains/backtesting`; research and Strategy 4 loader seams remain to review |
| `application/action_jobs.py` | Moved to `gates/workflows/portfolio_actions.py` Step 76; proposal state and persistence are in portfolio_engine |
| `gates/workflows/managed_risk.py` | Cross-domain guard moved to gates in Step 86; risk-reservation persistence belongs to `domains/portfolio_engine/risk_reservations.py` |
| `gates/workflows/portfolio_sync.py` | Coordinates broker account, ledger, market repository and portfolio inputs; actual broker/ledger operations remain in their domains |
| `gates/workflows/research_pipeline.py` | Pipeline workflow moved to gates in Step 85; run/stage state belongs to `domains/research/pipeline_repository.py` |
| `application/jobs.py`, `worker.py` | domains/operations; feature handler registration stays in gates/jobs/registry |
| `gates/operations.py`, `release_gates.py` | Separate operational policies into operations; readiness/CLI presentation stays in gates |
| `application/catalog.py`, `publication.py` | unused compatibility facades removed; artifact APIs remain in `domains/artifacts` |
| `application/runs.py` | Backtest-publication coordination in gates/workflows/backtesting |
| `gates/payloads.py` | Gate-owned payload parsing moved in Step 84; extract reusable business rules only where they have an independent domain owner |
| `application/kite_auth.py` | Moved to `domains/execution/kite_auth.py` with curated `domains.execution` API; config/env loading at gates |
| `application/security.py` | Shared redaction in platform_kernel/security; configure logging at gate startup |
| `application/runtime.py`, `composition.py`, `cli.py` | gates/runtime, composition, cli |
| All `application/*_web.py`, `application/web.py`, existing gate web modules | gates/http matching resource; retain blueprint names, URL paths, response contracts |
| `gates/session_coverage.py` | workflows/session_coverage over reference/market readers; no direct SQL |
| `gates/momentum_quality.py` | Audit pure signal/policy calculations into strategies/indicators; keep only multi-domain coordination in gates |
| `run.py` | Delegate `create_app`, `configure_logging` if callers need it, and `main` to gate entry points |

Review every `__init__.py`, tool, test, docs example, Makefile command, and packaging entry point as part of each move. The source map and live manifest now cover the retired `src/application` responsibilities; keep historical paths only in migration records.

## 7. Required boundary seams

1. **Reference versus market persistence:** inventory each `MarketRepository` method and table. Introduce owned public readers first, keeping SQL behavior stable. Move methods by aggregate. Replace multi-domain joins with snapshot readers assembled under one neutral read transaction when consistency requires it; avoid per-row calls.
2. **Strategy versus indicators:** strategies accept feature frames/evaluation results or an injected evaluator. Gate adapter owns indicator DAG execution. Remove the custom indicator import of `application.positional_trend`; classify true indicator features separately from signal policy and register callbacks through composition.
3. **Execution versus accounting:** ledger lives in accounting. Inject narrowly scoped fill/opening-position operations into execution. Preserve fill reconciliation idempotency and order/fill identifiers.
4. **Execution versus market/reference:** inject membership and price/risk checks. Replace broker's runtime import of MarketRepository and account module's strategy constant dependency.
5. **Research versus all calculation domains:** gate assembles versioned inputs; research stores research-owned outputs. No research service reaches into indicator cache or strategy tables.
6. **Corporate-action atomicity:** preserve the current transaction and replay/idempotency behavior. Use a neutral SQLite unit-of-work/connection contract passed to domain operations if they must share a transaction. Do not convert an atomic update into independent commits. Preserve recoverable publication sequencing.
7. **Background processes:** gates/lifecycle owns startup/shutdown. Market stream orchestration invokes execution auth, market quote storage, portfolio stop evaluation, and artifacts through public services. Domain constructors never start threads.
8. **Artifacts:** each producing domain supplies payload and provenance; the gate coordinates publication and projection writes using existing recovery semantics. Artifact IDs, categories, upstream IDs, checksums, and revision behavior are compatibility contracts.

Prefer batch readers and immutable snapshots over copying full histories repeatedly. Retain vectorized bulk research behavior and the single local writer configuration.

## 8. Implementation phases for Luna

Each phase should be independently reviewable. Do mechanical moves first, boundary changes second, extraction third; do not combine behavior changes with relocating modules.

### Work already completed in this worktree — 2026-10-03

The original Luna plan has since been implemented incrementally. Continue from the existing worktree and migration manifest; do not redo these moves. The current tree has gates-based app/runtime/CLI/HTTP composition, domains for artifacts, backtesting, execution, indicators, market data, operations, portfolio accounting/engine, reference data, research, and strategies, plus recursive import-boundary checks. `run.py` remains the root application entry point. The empty `src/application` package, unreferenced top-level `src.indicators`/`src.strategies` facades, and fully migrated `src.execution_gateway` package were retired in Steps 92–94.

Portfolio proposal persistence and lifecycle reads belong to `domains/portfolio_engine/proposal_store.py`; ActionJobs now coordinates through `gates/workflows/portfolio_actions.py`. The processed-state transaction remains caller-owned and is passed to the store so the ledger-version check and proposal update stay within the same immediate transaction. Backtest run-index persistence belongs to `domains/backtesting/repository.py`, and the pure replay/result engine is consolidated in `domains/backtesting/simulation.py`; replay job orchestration moved to `gates/workflows/backtesting.py` in Step 79, and Strategy 4 policy/replay moved to `domains/strategies/positional_trend_backtest.py` in Step 80; research service/input-reader coupling remains to review. The latest batches put instrument identities, token observations, dated reference snapshots, active-universe membership, exit eligibility, corporate-action event state, and its watermark in `src/domains/reference_data/repository.py`, with an owner migration in `src/domains/reference_data/schema.py`. Market tables now also have a `market_data` migration in `src/domains/market_data/schema.py`. All domain stores initialize directly at the current schema; historical numbered database migration chains and the legacy market namespace were removed because existing databases are not a compatibility target. Composite reads, the observed-session calendar, the join that resolves eligibility against benchmark bars, atomic event/market-bar adjustments, and the full corporate-action workflow are gate-owned. Corporate-action and liquidity payload workflows now live in gates; unused application compatibility shims were removed after caller audits. No database upgrade bridge is retained.

Current verification through Step 94 and test-tree consolidation: recursive import-boundary analysis passes with zero violations and 0 transitional imports via `tools/verify_import_boundaries.py`. Each test module follows a real source path and basename, and mixed-owner cases identified in the content audit have been split or moved to their owning source test module. The tree currently has 86 test modules for 129 source modules; source modules without tests do not get empty placeholders. Pytest discovery and `make test` use only `tests/`. Ruff lint and formatting checks pass for the reorganized test tree. Earlier direct checks cover deterministic market-history reads, revision hashes, adapter replay, Strategy 4 policy/simulation, StrategyRuntime cases, migration/recovery smoke checks, and owner-only schema initialization. Moving `ResearchJobs` changes the cache implementation fingerprint because it hashes the workflow source; this safely triggers cache rebuild under the same keying and correctness policy. Pytest was not run; the previous 453-pass result predates these repository and workflow moves.

### Follow-up priorities for Luna

1. Keep each domain schema as one current fresh-install definition. Do not add upgrade chains, legacy namespace detection, historical migration fixtures, or data compatibility transforms. Existing databases and stored artifacts are disposable during development.
2. Keep reference-data policy and snapshot calculations in the reference-data domain; keep payload parsing, job coordination, and publication in gates. Audit the gate/domain split for any remaining reference-data concerns.
3. Audit method callers for `MarketRepository`; replace the broad aggregate with injected domain APIs where practical. Keep only current, intentional composition APIs; do not retain transition facades.
4. Run focused market, reference, universe, ingestion, refresh, quote, session coverage, and corporate-action tests after any ownership changes. The test tree now mirrors `src/`; maintain its one-module-per-source-file rule. Run the complete test suite, lint, type, packaging, and resource checks at final proof; do not cite the historical 453-pass result as current.
5. Regenerate inventories/manifests after each owner move and keep the exact import-transition set accurate. The `src/application` package was retired in Step 92.

### Phase 0 — Baseline and migration manifest (complete)

- Read applicable repository instructions and existing inventories/repair status. Inspect working-tree changes and preserve unrelated work.
- Record every tracked Python source, current imports, exported symbols, routes/blueprint names, job type names, CLI commands, table/migration ownership, and path-based resources.
- Produce `docs/architecture/restructure-migration-manifest.md` with source, destination(s), owner, compatibility symbols, tests, and phase/status.
- Run the existing full suite, lint and type checks using the installed environment. Save outcomes; distinguish pre-existing failures from new failures. Do not treat historical passing counts as today's baseline.
- Build small representative synthetic fixtures for portfolio/research/backtest parity and capture API/job outputs using existing tests where possible. Do not use live trading or provider calls as verification.

Exit: every source has an owner and baseline evidence exists.

### Phase 1 — Neutral foundation and architecture enforcement (complete)

- Shared redaction now lives in kernel. Keep configuration/log handler creation in gates and maintain the recursive checks.
- Maintain recursive AST boundary checks over all source modules, including relative imports, TYPE_CHECKING imports and literal dynamic imports. Do not exempt entire domains or ignore nested packages.
- Keep the transition allowlist empty; reject new domain-boundary violations immediately.
- Separate framework-free core checks from permitted repository/provider imports. Ensure gates access only curated domain APIs.
- Maintain curated domain APIs and injected reader/writer contracts.

Exit: checks detect representative invalid imports and track all existing exceptions without hiding them.

### Phase 2 — Entry points and neutral stateful capabilities (complete)

- Gates now own app/runtime/composition/CLI/lifecycle and HTTP adapters under gates/http; retain the runtime compatibility contracts.
- Durable job stores/workers now belong to operations and catalog/publication to artifacts; strategy definitions belong to strategies.
- Keep `run.create_app` and `run.main` stable. Preserve `app.extensions['screener_services']` and commonly accessed service attributes during migration.
- Keep `screener-ops` at `src.gates.cli:main` and `screener = run:main`.
- Validate resource roots so wiki/templates/presets resolve in repository and installed-package runs. Do not rely on new `parents[n]` guesses.

Exit: application factory, health endpoints, CLI, workers and route map match baseline; no schema/data relocation.

### Phase 3 — Reference and market ownership (implemented; cleanup remains)

- Keep market/reference owner schemas separated and initialize only their current schema definitions.
- Keep provider fetch/normalization/calendar/universe logic in their domain owners and job orchestration in gates.
- Extract refresh, session coverage, corporate-action sequencing, and stream scheduling to gate workflows.
- Introduce batch snapshot contracts and preserve consistency of completed-session/membership checks.

Exit: reference/market tests and ingestion/coverage/quote integrations pass; gate workflows issue no direct business SQL except documented multi-domain atomic operations.

### Phase 4 — Indicators, strategies, research and backtesting (package ownership implemented)

- Keep the consolidated indicator and strategy packages free of duplicate implementations; remove any remaining duplicate logic only after parity tests.
- Keep evaluator and custom-indicator dependencies behind explicit contracts/adapters; investigate only if new coupling appears.
- Keep research/backtest/positional-trend job responsibilities separated into domain operations, owned persistence, gate workflows, and small handlers.
- Move remaining simulation loader SQL behind domain readers; keep tool CLI options stable.
- Move preset YAML into strategies/presets only after package-data and resource loading work; preserve the root path through an explicit transition if external tooling still uses it.
- Replace hard-coded source hashing with explicit implementation resource identities. Document whether a relocated implementation invalidates existing cache fingerprints; do not promise byte-identical hashes after edits. Preserve old artifact provenance and deterministic hashes for unchanged inputs within the new layout.

Exit: ranking/signal/backtest parity, DAG and cache invalidation, historical membership, bulk rebuild and artifact-lineage tests pass.

### Phase 5 — Portfolio, accounting and execution (package ownership implemented)

- Keep ledger/account/broker persistence and auth in accounting/execution domains. Replace any remaining strategy/membership/ledger dependencies with explicit ports where practical.
- Keep proposal state/persistence in portfolio_engine and cross-domain orchestration in gates; extract pure rules only when a clear owner and parity contract exist.
- Keep portfolio sync, managed-risk integration, corporate-action accounting and intraday-stop interactions in gates, using owning domain APIs.
- Preserve approval states, kill switch, live-execution defaults, account/profile isolation, partial fill reconciliation, and retry/idempotency.

Exit: existing approval, risk, accounting, broker, profile isolation and corporate-action integration tests pass without real orders.

### Phase 6 — Cleanup, unified tests, and final proof (in progress)

- Remove compatibility shims after all in-repository imports/tools/tests use new paths. If external consumers exist, document a short deprecation window with a removal condition; do not retain duplicate business implementations.
- Keep retired source roots absent; audit `db.py` and `test.py` separately before any retirement.
- Audit and retire `db.py` and root `test.py` if no supported callers exist; do not touch secrets, token files, runtime data, archives, or logs.
- The single `tests/` root mirrors `src/` by directory and module basename. Each `test_<source_module>.py` contains tests for exactly its corresponding source module; split previously mixed files and place each case with its owner. Cross-domain scenarios belong in the matching gate source module's test file. Do not add `tests/integration/` or another parallel integration root.
- Keep README, docs inventories, CodeTours, wiki examples, Makefile and packaging consistent with the mirrored tree. Pytest discovery and `make test` run only `tests/`; select integration behaviors by pytest markers if that distinction is useful, without adding a separate folder.
- Run the full suite, lint/type/security checks configured by the repository, package build/install smoke checks, and final import/path audits.

Exit: zero temporary boundary exceptions; no stale runtime references to old source paths; all manifest items completed and final evidence recorded.

## 9. Verification checklist

### Ordered continuation tasks for Luna

1. **Preserve the current tree and resolve the toolchain first.** Do not reset, clean, or broadly format this worktree. Use Python 3.13 as required by `pyproject.toml`; at plan authoring, the installed `.venv` provided Python 3.12 and system Python lacked pytest. Check current tool availability and select a compatible environment before claiming current full-suite results.
2. **Initialize databases cleanly.** Verify each domain store creates its complete current schema from an empty database. Existing database upgrades and legacy data preservation are out of scope.
3. **Audit broad market repository callers.** Inventory `MarketRepository` methods and their production callers. Replace direct aggregate use with domain-owned batch readers where a stable owner API exists. Keep cross-domain joins and atomic market/reference writes in the gate aggregate with an explicit transaction/consistency reason. Avoid per-row calls and preserve snapshot semantics.
4. **Review remaining mixed workflow seams.** Audit SQL used by `gates/session_coverage.py`, corporate actions, Strategy 4 input assembly, and backtesting/research workflows. Move only table-owned operations to domain repositories; preserve gate-level coordination, atomicity, artifact lineage, and source-hash/cache behavior. Add a focused behavior regression for each changed seam.
5. **Run the clean-install verification matrix.** With supported Python, run unit suites, architecture checks, formatting/lint, mypy, Bandit, package build/install, CLI help and fresh-schema smoke. Compare behavior against current canonical contracts. Do not run existing-database upgrade checks, legacy-data fixtures, or live provider/order flows.
6. **Keep the tests tree an exact source mirror.** Every `src/<relative path>/<module>.py` that has tests maps to `tests/<relative path>/test_<module>.py`; tests directories follow source directories, and each test module covers only its corresponding source module. Split mixed tests by the source behavior they exercise and preserve relevant assertions. Cross-domain behavior is tested alongside its owning gate workflow or HTTP adapter. Do not introduce `tests/integration/`, `tests/architecture/`, or an `integration_tests/` root. Keep pytest discovery and `make test` pointed at the single `tests/` root.
7. **Finalize the handoff.** Regenerate the source inventory and update the test manifest for the unified tree. Confirm no live imports of retired roots, no temporary architecture allowlist entries, and no business SQL in gates except documented multi-domain transactions. Record command results and unresolved compatibility risks in the migration manifest; update the phase table from evidence.

Use meaningful behavior tests around the seams rather than adding one test for every move. Keep each test module paired with its source module. Run targeted tests after each phase, the full suite at baseline and completion, and additional full runs when failures justify them.

Suggested PowerShell commands using the current project environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools/verify_import_boundaries.py
.\.venv\Scripts\ruff.exe check src tests tools run.py
.\.venv\Scripts\ruff.exe format --check src tests tools run.py
.\.venv\Scripts\python.exe -m compileall -q src tests tools run.py
.\.venv\Scripts\python.exe -m mypy src run.py
.\.venv\Scripts\python.exe -m bandit -q -r src run.py
.\.venv\Scripts\python.exe -m build
git diff --check
rg -n 'src\.application|src\.(market_data|reference_data|strategies|portfolio_engine|portfolio_accounting|backtesting|execution_gateway)' src run.py tests tools pyproject.toml
```

Check tool availability first. If expanded lint scope reveals old problems, report them separately; do not silently fix unrelated files. The final search must have no active old imports; historical documentation may describe old paths.

Verify:

- Current canonical routes, methods, blueprint endpoint names, HTTP status/error formats, SSE event names/cursors, and frontend resource loading; retired aliases return 404.
- Canonical durable job type strings, handler context signatures, cancellation/progress behavior and restart recovery; do not register retired job-name aliases.
- Same `create_app(config_class)` interface and test configuration behavior; no provider connection during factory-only smoke tests.
- Current physical data/token locations and config/env names; every domain schema initializes from an empty database as version 1. Existing migration histories/data are not supported.
- Same market normalization, completed-session membership, revision increments and quality semantics.
- Same strategy formulas/rankings, next-open timing, backtest outputs, proposal/accounting outcomes using fixed fixtures and tolerances appropriate to existing calculations.
- Same artifact lineage/recovery/idempotency, with explicitly reviewed hash/cache invalidation caused by source relocation.
- Installed wheel includes required presets/resources, resolves templates/static/wiki according to supported deployment, and exposes both CLI entry points. Test construction/CLI help without starting the server.
- Background worker, index poller and streams start once, keep current runtime defaults, and shut down through gate lifecycle.
- Recursive architecture checks prohibit domain-to-gate, domain-to-domain, gate-to-private-domain and kernel-to-domain dependencies.
- Gate persistence audit includes business SQL reached through helper functions; an import test alone cannot enforce table ownership.

## 10. Definition of done and handoff instructions

The restructuring is complete only when domain ownership is singular, all cross-domain use cases are visible in gates, `run.py` delegates startup, persistence belongs to its domain, and no obsolete parallel application/domain tree remains.

Luna should work in phase order and update the migration manifest after each reviewable batch. If a proposed split reveals an atomicity or provenance conflict, record the exact current behavior and implement the boundary preserving it before proceeding. Do not create broad exceptions merely to finish a phase.

Deliverables:

1. Implemented structure and public APIs/ports.
2. Completed source/table/job/route migration manifest.
3. Recursive boundary tests with no migration allowlist remaining.
4. Updated developer documentation and CodeTours.
5. Final validation report listing commands/results, pre-existing issues, parity fixtures, and intentional cache/resource compatibility decisions.

Keep domain names, the shared kernel exception, and root frontend assets as specified here unless repository evidence requires a documented adjustment. Do not add microservices, replace the database/framework, redesign the UI, change trading policy, or bundle outstanding overhaul features into this migration.
