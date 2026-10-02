# Phase 1: DAG Correctness, Cache Identity, Structured Logging and Quality

> Status: Implemented and reviewed on 2026-09-28. See exit evidence below.
> Authority: [Overhaul_Plan.md](../Overhaul_Plan.md).
> Dependencies: None; coordinate shared market migrations with Phase 2.
> Numbered tasks: 12.

## Confirmed Scope

Fix the existing DAG integration rather than replacing strategy calculations. Use the real frozen DagNode/reference-tuple API. Provide worker progress and quality contracts consumed by subsequent phases. No trading-rule changes.

New modules are identified at their introduction; phase-specific test files are planned additions. Other file names are existing integration targets. Numbered retained-strategy names appear only to identify migration sources; implemented runtime/config/UI uses momentum and positional_trend_following. Tests and migrations described here are future approved implementation work, not actions performed during plan review.

## Entry Checks

- [ ] Read the current migration namespaces and record the existing test baseline.
- [ ] Read DagNode/DagGraph/DagExecutor, StrategyRuntime and IndicatorNodeCache call paths.
- [ ] Inventory existing job event/SSE and sanitization interfaces.

## Exit Checks

- [ ] Approved operations have executable handlers and shared validation.
- [ ] Recursive hashes distinguish operand roles and changed ancestors while ignoring equivalent node names.
- [ ] Cache reads validate input and implementation revision.
- [ ] Structured progress survives reconnects/cancellation without leaking credentials.
- [ ] Quality checks flag 15% anomalies without excluding stocks or blocking buys solely because of the flag.

## Task 1.1: Record interfaces and migration baseline

**Files:** src/indicators/dag.py; src/indicators/registry.py; src/application/strategy_definitions.py; src/application/sqlite.py; src/application/market_repository.py; tests/test_sqlite_migrations.py.

1. List supported executor operations and every YAML/compiled-DAG consumer.
2. Record contiguous migration versions per namespace; allocate Phase 1 market migrations before Phase 2 additions. Never edit an applied version.
3. Record current targeted/full-suite failures separately from changes introduced later.

**Acceptance:** Migration ledger and baseline exist; no hypothetical constructor/dispatch API is used.

## Task 1.2: Unify approved-operation validation

**Files:** src/indicators/dag.py; src/application/strategy_definitions.py.

1. Remove operations without working handlers from APPROVED_OPERATIONS after auditing retained strategy usage.
2. Replace the local _OPERATIONS set with the canonical import; update YAML and compiled-definition validation.
3. Reject unsupported operations with node/operation context; do not remove valid percentile ranking outside the per-instrument DAG.

**Acceptance:** Every approved operation executes on representative input; unsupported operation definitions fail before publication.

## Task 1.3: Expose public parameter validation

**Files:** src/indicators/registry.py; src/indicators/dag.py; tests/test_dag_executor.py.

1. Rename _validate_parameters to validate_parameters.
2. Update adapter-internal calls, DAG calls and tests through repository-wide reference search.
3. Preserve validation behavior and error details.

**Acceptance:** No functional private-method callers remain; valid and invalid adapter parameters behave as before.

## Task 1.4: Compute graph-aware recursive hashes

**Files:** src/indicators/dag.py; src/application/strategy_runtime.py.

1. Validate references/cycles before computing hashes in topological order.
2. Hash provider/function/normalized parameters plus named dependency hashes or primitive field identities. Preserve argument roles and output selection.
3. Keep frozen nodes immutable: graph resolves string references; do not access child properties on tuples/strings.
4. Update unique_content_hashes, compiled graph read/write and runtime consumers to use the graph-resolved identity.

**Acceptance:** Renamed equivalent graphs match; changed ancestors, swapped operands and changed parameters differ; cycles/unresolved references fail.

## Task 1.5: Version indicator input identity

**Files:** src/application/node_cache.py; src/application/market_repository.py; src/application/research_jobs.py; src/application/strategy_runtime.py.

1. Add an instrument market-history revision identity updated transactionally only when stored OHLCV changes.
2. Extend cache reads/puts with expected market input revision and implementation/code identity; use the existing source_snapshot_id field deliberately or add version metadata via migration.
3. Do not accept a cached scalar merely because node/instrument/date match. Isolate old hash/cache entries from new graph identity.
4. Provide targeted invalidation/rebuild APIs for changed instrument histories; Phase 3 invokes them.

**Acceptance:** A changed input or implementation cannot hit stale cache; an unchanged fetch preserves reusable entries.

## Task 1.6: Use existing cooperative worker progress

**Files:** src/application/jobs.py; src/application/worker.py; src/application/market_jobs.py; src/application/research_jobs.py.

1. Use JobExecutionContext.checkpoint(progress=...) and JobStore.emit; do not introduce an imaginary emit_progress API.
2. Standardize stage, message, current, total, percent, instrument/account/strategy context and revision fields.
3. Checkpoint between provider batches and instruments; preserve lease renewal and cancellation behavior.
4. Preserve one-argument handlers while context-aware handlers receive the optional second argument.

**Acceptance:** Progress persists via events_after; cancellation/lease tests pass; totals and stage errors are readable.

## Task 1.7: Add per-module loggers and redaction

**Files:** run.py; src/application/security.py; src/application/market_jobs.py; src/application/research_jobs.py; src/application/pipeline_jobs.py; src/application/action_jobs.py; src/application/backtest_jobs.py; src/indicators/dag.py.

1. Use screener.<module> loggers and configure formatting once at startup.
2. Replace application debug prints while keeping intentional CLI output.
3. Apply existing sanitize_error patterns to persisted failures and redact api_secret/access_token/request_token payload fields.

**Acceptance:** Broker secrets never appear in logs/events/API errors; module and job context remain visible.

## Task 1.8: Persist data-quality events

**Files:** src/application/market_repository.py.

1. Add data_quality_events with event_id, instrument_id, as_of_date, check_type, severity, detail and detected_at; index instrument/date and detection order.
2. Implement record_quality_event and filtered/paginated get_quality_events using sqlite_connection and parameterized SQL.
3. Record source/expected/actual values and relevant job/revision identity in detail; avoid misleading duplicate events on unchanged reruns.

**Acceptance:** Fresh and upgraded stores support write/filter reads; invalid inputs fail cleanly.

## Task 1.9: Complete ingestion quality checks

**Files:** src/application/market_jobs.py; src/application/market_repository.py; src/application/exchange_calendar.py.

1. Validate OHLC bounds, positive finite prices and applicable volume rules in the ingestion path.
2. Check missing bars against completed trading sessions rather than calendar today; use TradingCalendar/session coverage and exclude exit-only data from membership completeness.
3. Warn for zero volume across more than five sessions and record unexplained absolute close-to-close gaps above configured 15%.
4. Anomaly flags retain the stock and allow normal BUY evaluation; corporate-action mismatch monitoring is implemented in Phase 3. Missing necessary data produces explicit diagnostics, not fabricated values.

**Acceptance:** Fixtures cover holidays, incomplete session, invalid OHLC, volume sequence and flagged-but-retained stocks.

## Task 1.10: Expose event and quality readback

**Files:** src/application/web.py; src/application/market_web.py; src/application/jobs.py.

1. Reuse existing job event readback/SSE cursor contracts for reconnectable structured progress.
2. Add quality-event readback in the owning market blueprint with bounded filters/limits.
3. Keep transport payloads documented for Phase 7 /logs and pipeline console.

**Acceptance:** Read-only API tests cover filtering, cursor continuation and redaction.

## Task 1.11: Add behavioral DAG, cache and quality tests

**Files:** tests/test_phase1_dag_fixes.py; tests/test_dag_executor.py; tests/test_node_cache.py; tests/test_durable_jobs.py.

1. Execute real operations; cover canonical validation, public adapter API and graph hash equivalence/transitive invalidation.
2. Test cache input revision mismatch, repeat fetch reuse, progress cancellation/reconnect and quality persistence.
3. Use Python source search only where necessary; no grep shell dependency or pass-only placeholders.

**Acceptance:** Targeted tests exercise real APIs and meaningful failure cases.

## Task 1.12: Verify Phase 1

**Files:** tests/; run.py.

1. Run targeted DAG/cache/worker/migration/quality tests and full suite against recorded baseline.
2. Check app imports and factory construction using a temporary database; do not launch live trading.
3. Record exit evidence and task completion in this file during approved implementation.

**Acceptance:** Zero new failures; all Phase 1 exit checks pass.

## Implementation evidence

- DAG operation validation is centralized in `APPROVED_OPERATIONS`; adapter
  parameter validation is public and used by compiled-definition validation.
- Graph hashes preserve input roles, resolve dependencies before hashing and
  distinguish ancestor/parameter changes while ignoring equivalent node names.
- Market-history revisions and implementation revisions participate in cache
  identity; changed bars invalidate derived indicators.
- Durable job checkpoints/events are used for progress; persisted payloads and
  worker failures are redacted through the shared security helpers.
- Market quality events persist bounded, filterable readback and ingestion keeps
  flagged stocks in research rather than treating a warning as an exclusion.
- Focused Phase 1 DAG/cache/worker/migration tests passed: **47 passed**.
- A full suite was started after the route-contract updates and ran beyond 67%
  without a reported failure in this environment, but its final process summary
  was truncated by the execution environment. This is recorded as an execution
  limitation, not substituted as completion evidence.
