# Phase 2: Daily Universe Snapshots, NSE Market Data and Exclusion Coverage

> Status: Plan only. Implementation requires explicit user approval.
> Authority: [Overhaul_Plan.md](../Overhaul_Plan.md).
> Dependencies: None for design; integrate Phase 1 shared migrations before Phase 2 schema additions.
> Numbered tasks: 18.

## Confirmed Scope

One immutable snapshot per collection day; subsequent runs reuse it and continue. Universe through rankings is manually launched. Remove BSE runtime support; retain current members, six NSE benchmarks and one extra exit-only session for excluded holdings. Phase 4 completes both-kind ranking orchestration and replay execution.

New modules are identified at their introduction; phase-specific test files are planned additions. Other file names are existing integration targets. Numbered retained-strategy names appear only to identify migration sources; implemented runtime/config/UI uses momentum and positional_trend_following. Tests and migrations described here are future approved implementation work, not actions performed during plan review.

## Entry Checks

- [ ] Inventory current CSV/token/universe/refresh consumers and all BSE wiring.
- [ ] Use actual TrackedInstrument/repository/provider payload APIs.
- [ ] Allocate market migration versions after Phase 1.

## Exit Checks

- [ ] Same-day reruns do not overwrite/redownload an existing successful universe snapshot.
- [ ] Series/token continuity preserves stable NSE ISIN instrument IDs.
- [ ] Both-strategy pipeline prerequisites originate from the same universe identity.
- [ ] Excluded members receive only the single next-session exit-price exception.
- [ ] Missing-opening fallback and automatic scheduling are outside scope.

## Task 2.1: Create universe snapshot schema

**Files:** src/application/market_repository.py.

1. Add universe_snapshots: snapshot_id, index_name, snapshot_date, source_url, source_hash, member_count, raw_csv, created_at; UNIQUE(index_name,snapshot_date).
2. Add universe_snapshot_members: snapshot_id, isin, symbol, company_name, industry, series; PRIMARY KEY(snapshot_id,isin) and parent FK.
3. Add lookup indexes and atomic insert-only repository transaction; never INSERT OR REPLACE a referenced snapshot.

**Acceptance:** Migration preserves current instruments/bars and enforces one daily snapshot.

## Task 2.2: Implement immutable snapshot repository operations

**Files:** src/application/market_repository.py.

1. Implement lookup by index/day, latest, as-of, earliest fallback, member list, snapshot list and arbitrary snapshot diff.
2. Insert parent/member rows atomically; concurrent same-day attempts return the first successful stored snapshot.
3. Preserve prior days/raw bytes. A current download records its actual collection day and cannot impersonate historical membership.
4. As-of replay chooses latest known snapshot not after decision date; before first snapshot use documented earliest fallback with lineage assumption.

**Acceptance:** Tests cover duplicate/concurrent insert, rollback, historical selection and diff.

## Task 2.3: Add validated NSE client

**Files:** src/application/nse_client.py (new); project dependency manifest.

1. Download NIFTY 500 CSV from the master URL with bounded timeout and HTTP validation.
2. Manage NSE cookies for corporate-action requests, refreshing on session failure with bounded retry.
3. Validate CSV columns/encoding and JSON structure; reject empty/error-page/invalid source responses.
4. Reuse an installed HTTP dependency or declare it in the actual dependency manifest; avoid hidden runtime imports.

**Acceptance:** Mocked CSV/cookie/error fixtures pass without live NSE access.

## Task 2.4: Create snapshot download handler

**Files:** src/application/universe_jobs.py (new); src/application/composition.py.

1. Check daily snapshot before requesting CSV; on hit return status=reused plus snapshot ID/members and advance stage.
2. Otherwise parse/normalize ISIN/symbol/series and reject duplicates/invalid source data before writing.
3. Compute SHA-256/raw member count, store once, diff against prior day and emit additions/removals/series transitions.
4. Register reference.download-nifty500-constituents with optional cooperative context.

**Acceptance:** First run stores; second run makes no source request and returns the same identity.

## Task 2.5: Extend instrument series contract

**Files:** src/application/market_repository.py; src/application/market_jobs.py.

1. Add series column through migration and extend TrackedInstrument plus upsert/read serialization.
2. Retain instrument_id=uuid5(NAMESPACE_URL, NSE:<isin>) identity and dated token observations.
3. Preserve historical tokens/bars when series changes; log transitions and invalidate only affected provider mapping metadata.

**Acceptance:** EQ-to-BE fixture preserves instrument ID and bar history.

## Task 2.6: Resolve universe members against Kite

**Files:** src/application/market_jobs.py; src/application/providers.py.

1. Replace CSV-filtered sync input with selected snapshot members.
2. Cache Kite NSE instrument dump per collection day; match actual tradingsymbol/series metadata without EQ-only filtering.
3. Upsert matched instruments/tokens and expose unresolved members explicitly; do not silently reduce the universe.
4. Keep resolution separate from history fetch so transient token failures remain retryable.

**Acceptance:** Mocked all-series dump resolves symbols and reports unresolved tokens.

## Task 2.7: Remove BSE runtime and import CSV dependencies

**Files:** src/application/market_jobs.py; src/application/composition.py; src/application/positional_trend_jobs.py; src/application/market_refresh.py; run.py.

1. Remove sync_bse_instruments/BSE_INDEX_SYMBOLS, BSE fallback and reference.sync-bse-instruments handler.
2. Remove nse_csv_path/bse_csv_path wiring once runtime reads use snapshots and Kite dump.
3. Audit broker/account/import interfaces for NSE-only supported strategy instruments without deleting retained historical market rows.
4. Update runtime/CLI/test call sites and worker payload allowlists.

**Acceptance:** No functional BSE refresh/resolution path remains; startup/legacy retained-data reads work.

## Task 2.8: Migrate strategy universe consumers

**Files:** src/application/positional_trend_jobs.py; src/application/research_jobs.py; src/application/positional_trend_backtest.py.

1. Replace positional _members CSV reads with snapshot members.
2. Pass explicit universe_snapshot_id into research/signal jobs rather than rereading mutable latest membership halfway through a run.
3. Provide as-of membership reader to replay; do not apply current universe retrospectively.

**Acceptance:** Research uses one pinned snapshot; replay respects known historical membership.

## Task 2.9: Register and resolve six benchmarks

**Files:** src/application/market_jobs.py; src/application/index_poller.py; src/application/market_repository.py.

1. Use NIFTY 50, NIFTY 500, NIFTY NEXT 50, NIFTY MIDCAP 150, NIFTY SMLCAP 250 and INDIA VIX as the target benchmark set.
2. Verify exact tradingsymbols against the actual Kite dump during approved implementation; surface missing mapping as a data error.
3. Remove unused prior index refresh set while keeping stored histories.
4. Resolve benchmark identity/token independently of equity snapshot membership.

**Acceptance:** All six mappings and quote/history readbacks are tested with provider fixtures.

## Task 2.10: Backfill new members and benchmark history

**Files:** src/application/market_jobs.py; src/application/market_refresh.py.

1. Initial history request starts 2021-01-01 or first available instrument data; store daily benchmark bars in market_bars.
2. Reuse fetch_bars/fetch_bulk_bars chunking, throttle, token lineage and coverage handling.
3. Subsequent runs request missing/incremental coverage; retries do not duplicate data.
4. Emit source revision changes through Phase 1 cache contract; indices with no traded volume use applicable quality rules.

**Acceptance:** New member backfill and incremental benchmark rerun are bounded/idempotent.

## Task 2.11: Persist universe-exit eligibility and execution coverage

**Files:** src/application/market_repository.py; src/application/universe_jobs.py; src/application/exchange_calendar.py.

1. Persist membership removal decision date/snapshot and next-trading-session target for exit-only price coverage.
2. Exclude removed members from ordinary refresh/buys immediately. For managed held exits retain one target-session bar/open record tagged exit-only.
3. Stop refresh after that session even if a live order remains open; ordinary membership never resumes because of an unfilled sale.
4. Missing target open is a diagnostic failure; suspended/next-available fallback is deferred backlog.

**Acceptance:** Only the target exit session is fetched; excluded membership stays excluded.

## Task 2.12: Update all refresh planners for membership rules

**Files:** src/application/market_refresh.py; src/application/market_jobs.py; src/application/index_poller.py.

1. Intersect regular refresh with snapshot members plus benchmark set.
2. Handle explicitly persisted exit-only requests separately from ledger.open_instrument_ids catch-all refresh.
3. Ensure per-symbol/bulk/reconcile/UI-triggered refresh follows the same restriction.
4. Include snapshot/date/revision in coverage reports; exit-only coverage cannot satisfy buy eligibility.

**Acceptance:** Held excluded instruments do not leak into regular/bulk refresh beyond exit exception.

## Task 2.13: Generate compulsory managed-holding SELL proposals

**Files:** src/application/action_jobs.py; src/application/universe_jobs.py.

1. Before BUY selection, compare managed strategy holdings with current pinned membership.
2. Generate reason=universe_exit SELL for absent instruments, with decision/target-session metadata.
3. Preserve approval: expected same-day user approval does not authorize auto-submission.
4. Exclude unrelated broker holdings and avoid repeated duplicate proposals for the same managed exit.

**Acceptance:** Mapped exclusions create SELL proposals; unrelated holdings do not.

## Task 2.14: Add manual pipeline data prerequisites

**Files:** src/application/pipeline_jobs.py; src/application/pipeline_web.py; src/application/composition.py.

1. Sequence universe → instrument/benchmark resolution → corporate detection/refresh → bars/quality → indicators/ranking branches.
2. Submit later prerequisite stages only after successful preceding completion, not as independently claimable jobs with implicit ordering.
3. Persist snapshot/revision context in pipeline/stage payloads and idempotency keys.
4. Do not add calendar scheduling; worker threads only process explicitly submitted work. Phase 5 adds explicit account/strategy portfolio sync input.

**Acceptance:** Stage trace proves prerequisites and same-day reused snapshot advance correctly.

## Task 2.15: Expose universe read/refresh interfaces

**Files:** src/application/reference_web.py; src/application/composition.py.

1. Add /api/v2/universe/members, /snapshots and /diff in an owning blueprint/service; parameterize IDs/dates and paginate lists.
2. Provide POST refresh that submits the universe job; GET remains read-only.
3. Return selected snapshot/date/hash/member count and additions/removals for Phase 7 widgets.

**Acceptance:** API fixtures cover invalid IDs, historic diffs, reused refresh and source failure.

## Task 2.16: Retire runtime static input files

**Files:** ind_nifty500list.csv; data/imports/NSE.csv; data/imports/BSE.csv; data/reference/nifty500/; application/config/test consumers.

1. Remove active runtime dependence on all listed CSV paths only after snapshot/bootstrap consumers work.
2. Apply master static-input cleanup; preserve stored market histories and database snapshot lineage.
3. Update examples/tests/docs to the new repository interfaces and actual Windows-compatible commands.

**Acceptance:** Fresh startup and manual pipeline require no legacy CSV file.

## Task 2.17: Add Phase 2 behavioral tests

**Files:** tests/test_phase2_universe.py; tests/test_reference_tokens.py; tests/test_market_coverage.py; tests/test_research_pipeline_jobs.py.

1. Cover snapshot reuse/concurrency/as-of selection, source failure, series transitions, unresolved tokens, six indices, backfill/incremental fetch.
2. Cover every refresh entry point, excluded held-stock exception, compulsory proposal and no future exit-price use in decisions.
3. Use mocked provider calls and portable Python assertions.

**Acceptance:** Tests detect incomplete ingestion/wiring rather than merely table/file existence.

## Task 2.18: Verify Phase 2

**Files:** tests/; run.py; docs/phases/phase2_universe_market_data.md.

1. Run targeted universe/token/coverage/pipeline tests and full suite.
2. Construct a fresh store and an upgrade fixture, exercise first/second daily pipeline runs with mocked Kite/NSE.
3. Record migrated schema/token/coverage and stage evidence.

**Acceptance:** All Phase 2 exit checks pass with zero new failures.
