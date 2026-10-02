# Phase 4: Named Strategies, Both Ranking Patterns and Retirement Cleanup

> Status: Implementation authorized and under review; completion is unproven. See [repair-status.md](repair-status.md).
> Authority: [Overhaul_Plan.md](../Overhaul_Plan.md).
> Dependencies: Phase 1 and Phase 2; integrate Phase 3 cache contracts for corporate-action tests.
> Numbered tasks: 12.

## Confirmed Scope

Retain momentum (factor_score) and positional_trend_following (event_signal). Migrate names everywhere; retire only benchmark-relative momentum/early momentum and remove their historical backtest outputs. Implement percentile stages/lineage and both-strategy manual ranking orchestration. Preserve protective-stop execution (Choice A).

New modules are identified at their introduction; phase-specific test files are planned additions. Other file names are existing integration targets. Numbered retained-strategy names appear only to identify migration sources; implemented runtime/config/UI uses momentum and positional_trend_following. Tests and migrations described here are future approved implementation work, not actions performed during plan review.

## Entry Checks

- [ ] Inventory numbered identities in definitions/jobs/routes/artifacts/action/backtest code and tests.
- [ ] Capture retained-strategy behavior including protective stops and next-open daily signals.

## Exit Checks

- [ ] Both named strategies compute rankings each pipeline run.
- [ ] Factor percentiles/weights-only reuse and direct event ranking have separate paths.
- [ ] Named migration preserves retained ledger/revision/artifact integrity.
- [ ] Removed-strategy historical backtests are ownership-scoped and shared/retained data survives.
- [ ] As-of universe exits execute next open without changing protective stops.

## Task 4.1: Inventory and migrate strategy identity

**Files:** strategies/momentum_quality.yml → strategies/momentum.yml; strategies/strategy4.yml → strategies/positional_trend_following.yml; src/application/strategy_definitions.py; src/application/strategy_runtime.py.

1. Use canonical IDs momentum and positional_trend_following and agreed descriptive display names.
2. Add restart-safe migration of strategy definition/revision ownership and mutable references; preserve revision/event/artifact identity and immutable-source audit integrity.
3. Publish canonical migrated definitions with explicit legacy provenance rather than editing checksummed historical blobs unnoticed.
4. Map legacy serialized IDs at historical read boundaries while active APIs/jobs/config/UI use only named identity.

**Acceptance:** Upgraded and fresh stores expose two named strategies without duplicate active revisions.

## Task 4.2: Rename runtime, jobs, APIs and tests consistently

**Files:** src/application/action_jobs.py; src/application/backtest_jobs.py; src/application/research_jobs.py; src/application/positional_trend_jobs.py; src/application/positional_trend_web.py; src/application/composition.py; run.py; tests/; scripts/; docs/.

1. Replace numbered retained dispatch branches, worker kinds/payloads, categories/display labels and test names with named equivalents.
2. Migrate persisted queued job/proposal/order/run projection references transactionally, keeping claim/idempotency integrity.
3. Rename strategy-specific test/module identifiers without removing positional_trend implementation.
4. Repository-wide audit excludes intentionally preserved raw historical source provenance; no numbered active strategy entry remains.

**Acceptance:** Named API/pipeline/action/replay requests and retained historical reads work.

## Task 4.3: Retire only removed strategy runtime

> Completion evidence: removed Strategy 2/3 source, tools, custom indicator and
> historical unit modules. Active positional-trend paths use only named runtime
> strategies and snapshot/database universes.

**Files:** strategies/benchmark_relative_momentum.yml; strategies/early_momentum.yml; src/application/early_momentum.py; src/application/early_momentum_rules.py; src/application/early_momentum_web.py; src/application/composition.py; run.py.

1. Remove active YAML/runtime/web/worker wiring for benchmark-relative momentum and early momentum.
2. Retire their persisted revisions; cancel their queued work through JobStore cancellation semantics rather than leaving unsupported jobs running.
3. Audit shared imports/helpers before deleting exclusive code and test files.
4. Keep Momentum and Positional trend code, action/backtest rules and regression coverage.

**Acceptance:** Startup/routing/worker registry has no functional removed-strategy dependency.

## Task 4.4: Delete removed historical backtest outputs safely

**Files:** src/application/backtest_jobs.py; src/application/catalog.py; src/application/publication.py; src/platform_kernel/artifacts.py; backtesting_results/; scripts/; tests/.

1. Inventory run IDs, payload strategy ownership, report paths, experiment/backtest artifact dependencies and removed-strategy saved outputs.
2. Use BacktestJobs.delete_run/catalog/store operations for owned DB artifacts; remove associated report files only after verifying resolved paths stay in intended output directories.
3. Delete removed-strategy backtest results/experiment outputs and stale UI/catalog links; preserve shared market history/reference inputs and retained-strategy saved runs.
4. Make cleanup restartable/idempotent; do not use broad filename deletion that can remove retained/shared results.

**Acceptance:** Before/after fixture proves owned removed outputs gone and retained/shared data untouched.

## Task 4.5: Introduce ranking-pattern dispatch

**Files:** src/application/ranking_patterns.py (new); src/application/research_jobs.py; src/application/strategy_runtime.py; src/application/positional_trend_jobs.py.

1. Implement FactorPercentileRanking for factor_score and DirectSignalRanking for event_signal.
2. Reuse existing retained factor transforms/weekly aggregation/tie rules and existing positional event metrics/rules.
3. Keep cross-sectional percentile work outside per-instrument DAG operations.
4. Expose shared result envelope with strategy revision, date, pattern and lineage while preserving pattern-specific columns.

**Acceptance:** Equivalent inputs reproduce current retained-strategy ordering under their own rules.

## Task 4.6: Add percentile snapshot persistence

**Files:** src/application/research_jobs.py; src/application/ranking_patterns.py.

1. Add research_percentiles master columns/PK plus snapshot metadata for date, universe, indicator inputs and computation identity.
2. Store raw factor/percentile values with input fingerprint independent of weights-only revision changes.
3. Include factor directions/transforms/normalization/missing-value/tie policy in reusable identity, preserving current behavior.
4. Persist atomically and associate scoring revision with reused percentile snapshot without mutating its source revision.

**Acceptance:** Stable input reuse and changed universe/definition identity are observable in DB tests.

## Task 4.7: Split factor stages A/B/C

**Files:** src/application/research_jobs.py; src/application/ranking_patterns.py; src/application/node_cache.py.

1. A computes/caches raw indicators; B computes cross-sectional percentiles; C applies weights/composite score/rank.
2. Weights-only changes skip A/B and rerun C. Indicator definition/code or universe changes rerun affected stages.
3. Expose separate stage results and cache-hit/progress metadata; do not bury full recomputation inside rank_week.
4. Preserve historical percentile/score/ranking publications on corporate-action cache rebuild; compute new date outputs from refreshed inputs.

**Acceptance:** Call-count/result tests prove weights-only reuse, definition/universe invalidation and historical freeze.

## Task 4.8: Complete direct event ranking path

**Files:** src/application/positional_trend_jobs.py; src/application/positional_trend.py; src/application/ranking_patterns.py.

1. Keep existing event eligibility and ADX/ADTV ordering plus strategy warmup/signal rules.
2. Route event indicators through cache/source revision contract; recompute indicators when adjusted history changes.
3. Preserve published historical ranking artifacts and saved backtest results; fresh signal/ranking dates use current inputs.
4. Use snapshot-scoped membership without factor-percentile dependency.

**Acceptance:** Retained positional event/supertrend/ADX contract regressions pass.

## Task 4.9: Fix pipeline acceptance and sequential branches

**Files:** src/application/pipeline_jobs.py; src/application/composition.py; src/application/pipeline_web.py.

1. Remove current factor-only rejection of event_signal strategies from ResearchPipelineJobs._request.
2. Default ranking branches to momentum and positional_trend_following on every manual run.
3. After data prerequisites, orchestrate factor A/B/C and event indicator/signal/rank branch using registered kinds and pinned input IDs.
4. Carry explicit portfolio account/strategy sync context separately; it never limits which ranking branches run.

**Acceptance:** Pipeline trace proves both branches complete and no factor job receives an event-only unsupported payload.

## Task 4.10: Attach lineage to research artifacts

**Files:** src/application/research_jobs.py; src/application/positional_trend_jobs.py; src/application/publication.py; src/application/catalog.py.

1. Write strategy_revision_id, indicator_code_hash, universe_snapshot_id, market_data_range and computed_at.
2. Include market-history/adjustment revision and percentile/signal dependency IDs in lineage.
3. Keep immutable publication/checksum and revision browsing APIs; do not rewrite stored saved-run payloads when inputs later change.

**Acceptance:** Lineage tests resolve dependencies and frozen artifact checksums remain stable.

## Task 4.11: Implement as-of universe exits in both replay paths

**Files:** src/application/backtest_jobs.py; src/application/positional_trend_backtest.py; src/application/positional_trend_jobs.py; src/application/market_repository.py.

1. Supply session-specific known membership to both simulators instead of static/current CSV membership.
2. On exclusion decision, prevent new entries and execute compulsory SELL at next trading session open using the one exit-only bar.
3. Keep decision/execution date, source snapshot and price revision in fills/reports; no future open used to choose decision.
4. Preserve existing protective hard-stop/intraday execution (Choice A); next-open applies to after-daily-analysis/universe exits.
5. Missing next-open special handling is backlog; fail/report missing input without synthetic fill. Saved runs remain unchanged.

**Acceptance:** Fixtures cover membership change, weekend/holiday next session, no-look-ahead exit, stop timing preservation and saved-run immutability.

## Task 4.12: Verify named strategies and rankings

**Files:** tests/test_phase4_strategy_cleanup.py; retained strategy/ranking/pipeline/replay tests.

1. Test migration restart, named worker/API dispatch, removed output cleanup, both patterns and stage reuse/invalidation.
2. Retain/rename protective stop and positional trend tests; do not improve pass rate by deleting retained failures.
3. Run targeted tests plus full suite and record fresh/upgrade two-strategy pipeline evidence.

**Acceptance:** All Phase 4 exit checks and zero-new-failure checks pass.
