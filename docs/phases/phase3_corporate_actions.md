# Phase 3: Corporate Actions, Verified Kite Refresh and Indicator Rebuild

> Status: Implementation authorized and under review; completion is unproven. See [repair-status.md](repair-status.md).
> Authority: [Overhaul_Plan.md](../Overhaul_Plan.md).
> Dependencies: Phase 1 and Phase 2.
> Numbered tasks: 10.

## Confirmed Scope

Kite is authoritative. BONUS/SPLIT may be temporarily self-adjusted once; later manual runs retry until verified Kite replacement. RIGHTS/DEMERGER are monitored without local factor adjustment. Rebuild indicators, preserve published historical percentiles/scores/rankings and saved backtests.

New modules are identified at their introduction; phase-specific test files are planned additions. Other file names are existing integration targets. Numbered retained-strategy names appear only to identify migration sources; implemented runtime/config/UI uses momentum and positional_trend_following. Tests and migrations described here are future approved implementation work, not actions performed during plan review.

## Entry Checks

- [ ] NSE client, pinned universe/token identity, market revisions and quality events are available.
- [ ] Inventory current CorporateActions.record/adjusted_bars consumers and legacy fact artifacts.

## Exit Checks

- [ ] SELF_ADJUSTED remains actionable until real verified Kite history replaces it.
- [ ] Retries/crashes cannot multiply prices twice or mark placeholder fetches complete.
- [ ] 15% anomalies retain stock/ranking/BUY evaluation and resolve automatically from ex-date evidence.
- [ ] Adjusted input revisions rebuild affected indicators, including ADX, without rewriting frozen outputs.

## Task 3.1: Persist event, state and verification provenance

**Files:** src/application/market_repository.py; src/application/corporate_actions.py.

1. Add corporate_action_events matching master fields and DETECTED/SELF_ADJUSTED/MONITORING/VERIFIED states.
2. Persist raw source payload, normalized ex-date, parsed ratio, baseline revision/selected prices, applied factor and attempt outcome.
3. Add durable detection watermark and actionable refresh query; NULL unmatched instruments instead of empty-string FK.
4. Use one stock/day event under confirmed scope; no local multi-action composition engine.

**Acceptance:** Fresh/upgrade schema persists matched/unmatched events and actionable states.

## Task 3.2: Normalize source dates and detect event types

**Files:** src/application/corporate_actions.py; src/application/nse_client.py.

1. Normalize accepted NSE date formats to ISO before identity and SQL comparisons.
2. Parse positive BONUS/SPLIT ratios; recognize RIGHTS/DEMERGER/Scheme of Arrangement for monitoring.
3. Ignore dividend/buyback price-adjustment processing as in master; preserve raw unparsed records with diagnostics.
4. Fetch from successful watermark with overlap; advance watermark after persistence, independently of latest market bar date.

**Acceptance:** Mock source fixtures cover variants, malformed dates/ratios and late repeated events.

## Task 3.3: Select affected tracked instruments and actual history fetch

**Files:** src/application/corporate_actions.py; src/application/market_jobs.py; src/application/market_repository.py.

1. Resolve stable ISIN to instrument/token and respect current/exit-only refresh eligibility from Phase 2.
2. Fetch complete relevant Kite history using existing chunked provider path, not comments or fake success.
3. Preserve pre-adjustment baseline and compare returned pre-ex-date observations with expected BONUS/SPLIT factor.
4. Do not treat days_since_ex/weekend as proof of adjustment; persist observed evidence.

**Acceptance:** An event cannot become VERIFIED without successful real provider response and bar persistence.

## Task 3.4: Apply temporary BONUS/SPLIT prices atomically

**Files:** src/application/corporate_actions.py; src/application/market_repository.py.

1. For still-unadjusted Kite history with a parsed valid factor, scale OHLC only before ex-date once.
2. Persist market revision, baseline and SELF_ADJUSTED state in one transaction.
3. Check application provenance on restart/retry; retain existing provider volume until authoritative Kite replacement.
4. Do not locally adjust RIGHTS/DEMERGER or events with invalid factor.

**Acceptance:** Crash/retry fixtures cannot double-adjust; bars/state/revision either all commit or all roll back.

## Task 3.5: Retry all SELF_ADJUSTED work on later manual runs

**Files:** src/application/corporate_actions.py; src/application/pipeline_jobs.py.

1. Select DETECTED/SELF_ADJUSTED/MONITORING work, including events not newly detected that day.
2. Re-fetch SELF_ADJUSTED history, verify against preserved baseline, atomically replace with authoritative bars and transition VERIFIED.
3. Failed/still-unadjusted responses remain actionable with attempt diagnostics.
4. No local temporary update sets COMPLETED or disappears from pending verification query.

**Acceptance:** Two-run test performs local temporary update followed by verified Kite replacement.

## Task 3.6: Monitor rights/demerger and unexplained gaps

**Files:** src/application/corporate_actions.py; src/application/market_repository.py.

1. Use configured 15% absolute discrepancy/gap criterion and retained ex-date comparison evidence.
2. Flag/refetch without local rights/demerger factor calculation.
3. Keep stock in universe/rankings and permit BUY evaluation subject to ordinary checks.
4. Complete monitoring automatically when refreshed relevant ex-date discrepancy resolves; a later unrelated quiet day is not proof.

**Acceptance:** Monitoring state/quality events and flagged-but-buy-eligible behavior are tested.

## Task 3.7: Rebuild affected indicator history

**Files:** src/application/node_cache.py; src/application/research_jobs.py; src/application/positional_trend_jobs.py; src/application/strategy_runtime.py.

1. Invalidate instrument input revisions and rebuild dependency histories with sufficient warmup after confirmed/local bar change.
2. Rebuild Momentum and Positional trend indicators including ADX, ATR/stop inputs and ancestors affected by changed history.
3. Do not overwrite historical percentile/scoring/ranking publications or saved backtest reports; fresh dates use updated indicators.
4. Separate cache refresh result from publication result so ordinary rebuild helper cannot silently rerank history.

**Acceptance:** Cache changes while frozen historical output/checksum fixtures remain identical.

## Task 3.8: Remove double-adjustment risk in existing consumers

**Files:** src/application/corporate_actions.py; src/application/market_web.py; src/application/backtest_jobs.py; src/application/composition.py.

1. Adapt CorporateActions.record/adjusted_bars integration and existing API consumers to authoritative adjustment basis.
2. Do not apply legacy facts again to already adjusted market_bars.
3. Preserve old saved backtest artifacts; new runs record market/adjustment revision lineage.
4. Distinguish market-price changes from Phase 5 broker share/cost reconciliation.

**Acceptance:** Legacy reader fixture cannot apply a split twice; new replay receives declared basis.

## Task 3.9: Wire one pipeline stage and job handlers

**Files:** src/application/composition.py; src/application/pipeline_jobs.py.

1. Register reference.detect-corporate-actions and durable refresh work on the shared NSE client.
2. Orchestrate once after instruments and before bars/quality/indicator branches.
3. Use context checkpoints and stage result with affected instrument/revision lists; do not call the same stage twice from nested fetch paths.

**Acceptance:** Pipeline stage order and repeat-run verification work are observable.

## Task 3.10: Add behavioral verification

**Files:** tests/application/test_corporate_actions.py; integration_tests/gates/test_corporate_actions.py; integration_tests/application/test_artifact_lineage.py; tests/domains/indicators/test_node_cache.py.

1. Cover parsing/dates/null reference, watermark overlap, actual fetch, once-only local update, retries/failures/atomic replacement.
2. Cover rights/demerger no-local-update, automatic monitoring resolution, no anomaly exclusion, no double adjustment and frozen saved outputs.
3. Run targeted tests and full suite; no live broker requests.

**Acceptance:** All Phase 3 exit checks and zero-new-failure baseline comparison pass.
