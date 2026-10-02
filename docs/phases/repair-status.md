# Phase repair status — 2026-09-29

The user confirmed that all seven phases and `../Overhaul_Plan.md` define the
complete scope and authorized building on the existing development. The
[98-task acceptance checklist](acceptance-checklist-20260929.md) preserves the
full completion target. No phase is newly certified complete by this report.

## Defined-task focus — Phase 1 follow-up

Work resumed on the original numbered tasks after the WebSocket clarification.
Tasks 1.7–1.10 now have additional verified repairs:

- Quality checks evaluate the resulting stored sequence across sparse incoming
  dates and six successor bars after historical corrections. They no longer
  invent gaps or zero-volume streaks by skipping intervening stored sessions.
- Corrected closes/volumes are checked against affected stored successor bars.
  Warning records preserve the actual bar source plus validation source; bars
  remain available and unchanged reruns keep the same history revision.
- Benchmarks identified by `INDEX:` do not produce stock traded-volume streak
  warnings. Quality filters and unknown instrument writes fail as domain errors.
- Embedded credential assignments in messages, provider URLs and formatted
  log/traceback output are redacted. Camel-case credential fields are handled.
  Quality details use the shared redaction contract before persistence.
- Real worker failure/event API and quality readback tests cover redaction,
  continuation cursors, filters, pagination and unchanged-event idempotency.

Evidence: full suite **379 passed in 22.50 seconds** using
`.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .phase-defined-task-final --tb=short`.
The final quality-detail redaction refinement was additionally verified by all
**19 tests** in `tests/test_phase1_quality_repairs.py`; edited-file Ruff and
`git diff --check` pass. These results do not certify all Phase 1 criteria.
Completed-session/membership coverage diagnostics, consistent progress fields,
and full per-task migration/cache/DAG evidence still need acceptance review.

## Phase 1 acceptance evidence — 2026-10-01

- All 24 approved DAG operations execute against representative inputs; the
  published manifest and real multi-output indicator providers are tested.
  Unknown compiled operations and custom strategy top-level operations reject
  before revision publication.
- Cache reads and writes require both market-history and implementation
  revisions. Legacy/mismatched rows cannot hit, and nonfinite values reject.
  Implementation identity includes installed indicator, pandas and NumPy
  versions plus strategy source; unchanged history remains reusable.
- Fresh application construction verifies contiguous namespaced migrations and
  health/quality readback. Completed-session coverage uses historical NSE
  membership and six observed benchmark sessions; current/incomplete sessions
  are excluded. Quality warnings leave flagged stocks in research scoring.
- Cooperative bulk progress/cancellation, SSE event cursor continuation and
  error redaction have behavioral coverage.
- Full regression after the publication and quality changes: **440 passed in
  49.17 seconds** with `.\.venv\Scripts\python.exe -m pytest -q -p
  no:cacheprovider --basetemp .phase1-final-regression --tb=short`.

This evidence advances Phase 1, but its exit checklist still needs a complete
criterion-by-criterion audit before certification. Phase 2 direct and bulk BSE
history entry points now reject unsupported runtime fetches; the targeted
Phase 2/provider selection passed **18 tests**. The manual prerequisite now limits benchmark history requests to the six
approved NSE symbols, with a retired-index regression fixture. The subsequent
full regression passed **441 tests in 121.09 seconds** with
`.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp
.phase2-runtime-regression --tb=short`. Snapshot-aware
bounds across all fetch entry points remain open. The legacy CSV-backed
`sync_instruments` handler remains active and must be removed after its
callers are migrated to snapshot resolution; historical market rows should
remain readable.

## Phase 2 ingestion and BUY-boundary repairs — 2026-10-01

- Removed the registered static-CSV NSE sync and YFinance day-0 enrichment
  handlers and their legacy methods/constructor fields. Fresh-app tests prove
  snapshot resolution remains registered and both retired handlers are absent.
- Direct and bulk Kite history requests now require an instrument in the latest
  immutable NIFTY 500 snapshot or one of the six NSE benchmarks. Excluded
  stocks can request only their recorded next-session exit bar with an explicit
  `exit_only` marker. Migration 16 separates exit-only fetch coverage from
  regular coverage and upgrades existing regular windows without losing them.
- Regular refresh planning uses the latest snapshot even when the requested
  bar range is historical. The manual prerequisite excludes old index symbols.
- Ranked Momentum, positional and manual BUY selection consult current NSE
  membership. Approval of an old BUY proposal and broker submission of an old
  BUY intent recheck membership; SELL-only positional proposals remain usable.
  Behavioral fixtures prove an exclusion neither reaches the broker gateway
  nor reuses a stale positional proposal identity.
- Focused history/planner/migration selection passed **68 tests**; action and
  broker boundary selections passed **31**, **2**, and **8** tests at their
  respective revisions. Edited-file Ruff and `git diff --check` passed.

Full-suite verification after the final approval/submission guards passed
**443 tests in 158.51 seconds** with `.\.venv\Scripts\python.exe -m pytest -q
-p no:cacheprovider --basetemp .phase2-buy-submit-final --tb=short`.
Phase 2 remains open: historical pipeline membership windows, exit-only
session provenance, remaining BSE/application-cap runtime selectors, and all
other numbered acceptance criteria still require review.

## Active positional selector retirement — 2026-10-01

New positional signal, action and backtest requests now accept only the
snapshot-backed NIFTY 500 universe. Active signal sessions and fingerprints
use NSE; the obsolete CSV constructor argument is removed. The legacy
application-cap replay reader remains for stored historical inspection, but
new runs cannot select it. Focused positional/legacy-read tests passed
**25 tests**; edited-file Ruff and `git diff --check` passed. Full regression
passed **443 tests in 273.02 seconds** after active selector retirement.
This does not certify Phase 4: named identity migration, stage reuse and
remaining numbered criteria are open.

## Momentum as-of replay progress — 2026-10-02

- Momentum replay now filters entries by the snapshot known before each
  execution session. Snapshot removals schedule a compulsory `UNIVERSE_EXIT`
  at the next observed NIFTY 500 benchmark session open. The normal portfolio
  engine retains hard-stop precedence; missing target stock opens fail with a
  specific diagnostic rather than using a later price.
- One observed session after the requested end can settle a pending exclusion.
  Its fill carries the decision date, universe snapshot, bar snapshot and
  market-history revision. It is present in the report but excluded from the
  requested period's equity curve, trade counts and return metrics.
- Behavioral fixtures cover an intervening unobserved session, changed exit
  prices that leave prior valuation and saved artifacts unchanged, and missing
  target opens, protective hard-stop precedence and no re-entry on the exit
  session. Focused replay/portfolio selections passed **46** and **15**
  tests at their respective revisions; latest integration fixture passed.
  Edited-file Ruff and `git diff --check` pass. The final full suite passed
  **446 tests in 34.63 seconds** with `.\.venv\Scripts\python.exe -m pytest
  -q -p no:cacheprovider --basetemp .phase4-momentum-full --tb=short`.

Phase 4 remains open for the rest of task 4.11 acceptance, named identity
migration, both-strategy ranking orchestration, stage reuse and the other
numbered exit criteria.

## Phase 3 retry and monitoring evidence — 2026-10-02

Corporate verification now records durable attempt outcomes when valid Kite
responses still fail ex-date, coverage or temporary-adjustment comparison
checks. The event remains actionable and repeated attempts increment its
counter without changing bars. RIGHTS/DEMERGER monitoring writes a deduplicated
`corporate_action_mismatch` warning with ex-date, threshold and market revision;
verified resolution writes an INFO observation. A new market migration stores
selected pre/post prices and provider comparison evidence alongside the original
market revision. Local BONUS/SPLIT adjustment now requires the exact completed
ex-date bar and checks whether stored history already appears adjusted; those
cases remain actionable and do not multiply prices again. Kite verification
compares its selected pre-ex-date close with the preserved baseline and parsed
factor before accepting replacement. Unresolved comparisons remain actionable
and write a corporate-action quality event. The targeted corporate, repair and
migration selection passed **74 tests**; Ruff and `git diff --check` pass for all
edited files. The complete suite passed **452 tests in 36.71 seconds** with
`.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp
.phase3-corporate-full-final --tb=short`. Phase 3 still needs complete
indicator-history rebuild, frozen-output and legacy replay-basis acceptance.

## Implemented repairs

- Corporate provider responses validate OHLCV, dates and duplicates before
  changing history. Replacement bars, history revisions and event state commit
  together; failed transitions roll back. RIGHTS/DEMERGER refreshes persist,
  use configured anomaly thresholds and require the relevant ex-date evidence.
- BONUS/SPLIT processing tries verified provider history before a temporary local
  factor. Repeated detection can resolve missing instrument identity without
  resetting event state. Incomplete pre-event histories remain actionable.
- Refresh planning excludes unrelated/non-member holdings from regular refresh
  and queues only the declared single exit session for exclusions. Unknown future
  sessions remain explicitly pending; observed NSE benchmark sessions resolve
  them. Existing exit records survive the nullable-target migration.
- Current universe downloads use actual collection dates in the India timezone.
  Concurrent collectors use the first committed snapshot identity downstream.
- Positional replay loads all-series historical snapshot members, uses as-of
  membership with the documented earliest fallback, and records compulsory
  exits at the exact next observed open. Missing opens do not use later prices.
  One extra session settles exits without feeding entries or period valuation.
- Published research lineage rejects changes and preserves identical retries.
  Empty-feature bulk research no longer fails on conditional hash imports.
- Broker submission and receipt recovery share stable tags; existing intent
  tags retain their prior format. Replay fills carry persistent instrument IDs.
- Obsolete fixtures now cover confirmed snapshot, account-scoped setup,
  external-flow reason, live-cost and inline-pipeline contracts. Required
  validation was preserved; retired fixed-universe behavior was not restored.
- README links now point to existing documentation and identify current scope.

## Pending WebSocket explanation — user clarification

**Pending; no further implementation is being pursued separately from the defined
phase tasks.** The user clarified that WebSocket subscriptions should contain
only stocks for which an action needs to be taken. Historical bars are added by
the separate pipeline; there is no WebSocket-triggered session-end historical
addition. This explanation applies when a defined phase task requires live prices;
it does not expand the phase scope or change daily/universe AMO timing.

The connection/quote-store work already added is retained as existing development,
but it is not certified as a completed execution workflow and is not automatically
started. Its current arbitrary caller-selected subscription list does not yet enforce
the pending-action-only requirement. See [pending live-price notes](../live-prices.md).
The previous same-day sizing/timing questions are deferred with this work.

## Evidence

- Original full-suite baseline: **308 passed, 15 failed**.
- Earlier complete suite after live quote integration: **360 passed**,
  23.37 seconds. Command:
  `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .phase-live-full-suite --tb=short`.
- Live quotes, provider and alert subset: **22 passed**, including connection failure
  and stopped-lease protection (also included in the complete suite).
- Ruff passed for every source/test/tool file edited in this batch;
  `git diff --check` passed and the isolated acceptance probe completed.
- Generated phase fixtures and SQLite sidecars are now excluded from Git.
  Only this review's generated fixture entries were removed from the index;
  the fixture files themselves were preserved.
- Additional targeted checks passed: 38 universe/migration/startup checks,
  70 corporate checks, and 29 broker/migration/repair checks at their respective
  code revisions. These subsets support specific repairs, not whole-phase completion.
- New behavioral checks are in `tests/test_phase_completion_repairs.py`.
  Existing acceptance probes use temporary databases and a fake broker.

## Remaining acceptance work

1. Verify all numbered entry/task/exit criteria for DAG, logs and quality checks.
2. Integrate snapshot-aware bounds and exit-only coverage through every direct,
   bulk and manual prerequisite ingestion path; complete future-session calendar
   integration after the pending source clarification.
3. Audit provider baseline evidence across the corporate-action paths, then
   prove affected Momentum/Positional indicator rebuilds (including ADX), frozen
   publication checksums and legacy replay-basis acceptance.
4. Implement as-of universe exits in Momentum replay, complete persisted named
   identity migration, ownership-scoped retirement cleanup and stage-reuse
   acceptance. Positional replay improvements do not certify Momentum replay.
5. Implement managed-only broker reconciliation, verified split/bonus accounting,
   discrepancy review, imported strategy stops/setup valuation and explicit
   operated-portfolio sync in each manual pipeline.
6. Verify/fix global aggregation, broker buying power, reservations through partial
   fills/cancellation and imported day-P&L/return/risk workflows.
7. Complete broker authentication/import, review, capital and editable strategy
   browser workflows; validate themes, accessibility, mobile and SSE lifecycle.

## Pending clarification

The future NSE trading-calendar source is unresolved. The user was asked whether
it should be an official NSE holiday calendar, observed-session-only resolution,
or another specified source. No guessed next-calendar-day target is required
for the repaired snapshot collector. This clarification does not prevent other
phase repairs from continuing.
