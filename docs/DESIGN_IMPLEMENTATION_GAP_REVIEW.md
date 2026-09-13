# Design-to-Implementation Gap Review

**Reviewed:** 2026-09-11  
**Authority:** `MODULAR_MONOREPO_DESIGN.md`  
**Scope:** the current uncommitted working tree, `run.py`, backend packages,
tests, packaging, CI, and operator documentation. This is a code/test review;
it is not a live-provider, broker, load, disaster-recovery, or production-data
migration drill.

## Executive verdict

The replacement code is a useful architectural skeleton, but it is **not
release-ready as a stock screener, authoritative paper ledger, or backtesting
system**. The direction is sound: domain modules are framework-free, jobs and
catalog data share a namespaced SQLite file, migrations are atomic, artifacts
are written through private staging directories, and live broker dispatch is
disabled.

The earlier review overstated several closures. The test suite proves 26 happy
paths, but focused repros found correctness failures in same-bar execution,
ranking ties, cancellation, job lease ownership, ledger idempotency, artifact
recovery, secret redaction, readiness, and SQLite connection lifecycle. The
working tree also removes the legacy screening/API implementation before
replacement parity exists, contrary to the additive migration rule.

Release-gate status:

| Gate | Status | Reason |
|---|---|---|
| Architecture skeleton | Conditional pass | Package direction is good; persistence ports and dependency matrix remain incomplete. |
| Research parity | Fail | Only `close` and one-period return exist; percentile/score artifacts and tie semantics are incomplete. |
| Backtest correctness | Fail | Declared fill model is not applied and same-bar look-ahead remains. |
| Concurrent research | Fail | No running worker is composed; cancellation and lease ownership are unsafe. |
| Ledger cutover | Fail | Fill-only ledger, payload-blind idempotency, no lifecycle/reconciliation, not composed into the app. |
| Paper trading | Fail | `PaperBroker` returns an in-memory report and writes no ledger event. |
| Live execution | Correctly disabled | No live adapter should be enabled until paper/recovery gates pass. |
| Legacy retirement | Fail | Legacy files/routes are deleted in the working tree before capability and data-migration parity. |
| Operations | Fail | Restore helper exists, but no drill evidence; readiness can create a missing database and CI is not green under its own lint command. |

Severity meanings:

| Severity | Meaning |
|---|---|
| P0 | Can misstate financial/research results or duplicate/lose authoritative work. |
| P1 | Violates a target invariant or blocks a stated release gate. |
| P2 | Material resilience, security, operability, or maintainability gap. |
| P3 | Optimization to apply after correctness is established. |

## Validation evidence

| Check | Result | Interpretation |
|---|---|---|
| `pytest -q` | **26 passed** in 1.20 s | Existing tests are green. |
| Coverage | **84% statements** | Useful breadth, but branch/error-path coverage is missing in critical workflows. |
| `compileall` | Pass on local Python 3.12.14 | Syntax/import smoke check only; project declares Python >=3.13. |
| `pip check` | Pass | Installed packages have no reported dependency conflicts. |
| `ruff check src tests run.py` | **Fail: 119 findings** | Includes 17 import-format failures, one broad exception, one unused import, and many style findings. The committed CI runs this command and would fail. |
| `ruff format --check` | **Fail: 40 files** | Formatting is not at the configured gate. |
| `black --check` | **Fail: 41 files** | The local 3.12 runtime also cannot perform Black's 3.13 target safety parse. |
| Type/security analysis | Not executed | `mypy` and `bandit` are in Poetry-only dev dependencies, absent from the local pip environment, and absent from CI. |
| Focused behavioral repros | **8 failures confirmed** | Cancellation completed as `SUCCEEDED`; different ledger payload reused the prior result; corrupt payload was cataloged; a missing DB was created and reported ready; nested/API-key secrets were persisted; equal values received 0/100 percentiles; a close exit funded a same-date open buy; SQLite files remained locked on Windows. |

The working tree was already substantially dirty when reviewed. This document
does not assume that deleted legacy files or new replacement files have been
committed, and no unrelated changes were reverted.

## Gap status against the previous review

| Previous gap | Current status | Evidence |
|---|---|---|
| G-01 publication protocol | Partial | `ArtifactPublisher.recover()` exists, but recovery trusts unchecked manifests/payloads and has no durable pre-publication state. |
| G-02 catalog/recovery states | Partial | Manifest fields and `MISSING` exist; qualification, revocation, tombstones, retention, and corruption quarantine do not. |
| G-03 shared SQLite coordination | Partial | Jobs/catalog use `system.db`; ledger is not in `ApplicationServices`, and no writer coordinator spans them. |
| G-04 atomic migrations | Closed by unit test | Individual statements and version insert share one explicit transaction; intentional failure rolls back. |
| G-05 durable executable jobs | Partial | Claims and a worker primitive exist; ownership, heartbeat, retry, cancellation, bounded concurrency, and runtime wiring do not. |
| G-06 run/fill manifest | Partial | Contracts exist; fill settings are inert and output/quality/catalog requirements are incomplete. |
| G-07 timing/risk policy | Open | Swap reinvestment is deferred, but score/stop exits can still finance same-date open buys. |
| G-08 event ledger | Open | Ledger still records fills only; paper broker bypasses it. |
| G-09 monetary/idempotency fidelity | Open | Same key with different fills succeeds; currency, fees, timestamp, metadata, and chronology are absent. |
| G-10 research pipeline | Partial | Two built-ins and an in-memory ranker exist; full strategy factors, eligibility, separate snapshots, and parity do not. |
| G-11 point-in-time data | Partial | Alias/universe/calendar/corporate-action value types exist; token history, benchmark, fundamentals, publishing/resolution, and adjusted-bar workflow do not. |
| G-12 provider safety | Partial | Single-ticker yfinance shape is handled; raw evidence, metadata, retries, calendars, and robust redaction are absent. |
| G-13 local HTTP guardrails | Mostly closed | Loopback opt-in, constant-time token comparison, and 64 KiB cap exist; deployment/TLS/audit evidence does not. |
| G-14 API boundaries | Partial | AST test blocks selected libraries/internal imports in domain modules; it does not enforce the documented package dependency matrix. |
| G-15 operational evidence | Partial | CI and restore helpers exist, but CI lint fails, paths are stale, and no restore/load/security/release evidence is emitted. |

## Confirmed findings

### R-01 — The portfolio engine still performs look-ahead execution

**Severity:** P0  
**Evidence:** `portfolio_engine.evaluate()` evaluates a score exit at the
current bar close, immediately adds the proceeds to cash, then buys another
instrument at the **same bar open**. Intraday-stop proceeds can likewise fund
an earlier open. The swap path alone has a `deferred_reinvestment` safeguard.
A focused case produced `SCORE_EXIT @ 110` followed by `BUY @ 100` on the same
date.

`FillModelRevision` declares `close → next_tradable_open`, slippage, and fees,
but `backtesting.run()` accepts no fill-model object and applies none of those
settings. A manifest ID therefore claims semantics the engine does not enact.

**Impact:** backtests can use future information and overstate buying power and
returns. Two different fill-model revisions can produce identical fills.

**Required correction:** split signal/decision time from execution time. Emit
order intents at close, execute them only on the next tradable bar, and credit
cash only when the sell fill occurs. Apply side-aware slippage and fees in one
shared fill function used by backtest and paper execution. Add golden tests for
score exits, gap stops, intraday stops, swaps, holidays, and missing next bars.

### R-02 — The job lease and cancellation protocol is unsafe

**Severity:** P0  
**Evidence:** `ops_jobs` stores no lease owner or claim token. `complete()` and
`fail()` accept only a job ID, so a stale worker can commit after another worker
reclaims the expired lease. There is no heartbeat. A running cancellation sets
only `cancel_requested`; `JobWorker` checks for status `CANCELLED`, so a handler
that requests its own cancellation completed as `SUCCEEDED` in a focused repro.
Attempts are unbounded and `FAILED` is terminal with no safe retry command.

No worker is created or run by `ApplicationServices`/`run.py`. The HTTP API can
return `202` for arbitrary or unsupported job kinds that no process will ever
claim.

**Impact:** duplicate side effects, cancellation races, permanently queued
work, and misleading API acceptance.

**Required correction:** persist `lease_owner`, random claim token, lease
expiry, heartbeat, max attempts, next-attempt time, and terminal error/result.
Require the current claim token on heartbeat/complete/fail and make every
update conditional on owner + unexpired lease. Make cancellation cooperative
through a handler context and atomically resolve cancel-versus-complete. Wire a
real worker with a closed registry of accepted job schemas before exposing job
submission.

### R-03 — Ledger idempotency can silently accept a different financial command

**Severity:** P0  
**Evidence:** `ledger_commands` stores only `(account_id, idempotency_key,
resulting_version)`. Reusing a key with a different fill batch returned version
1 for both commands in a focused repro. `CommandMetadata` is not used. Event
JSON omits currency, fee/tax, execution timestamp, command metadata, source,
and correlation IDs; projection reconstructs all money as default INR.

The ledger models neither capital/cash events nor decision, order, attempt,
approval, reconciliation, correction, corporate-action, and audit events.
`PaperBroker.submit()` writes nothing to it, and the ledger is not part of
`ApplicationServices`.

**Impact:** a client bug can be reported as an idempotent success while the
requested economics differ. Paper reports are not authoritative or
reconcilable.

**Required correction:** hash a canonical command envelope and persist the
hash, type, metadata, and result; reject a reused key with a different hash.
Normalize money/currency/fees/timestamps into validated event fields. Implement
the order lifecycle and make both paper and future live adapters execute only
through the same transactional command handler.

### R-04 — Artifact recovery can catalog corrupt or incomplete output

**Severity:** P0  
**Evidence:** recovery enumerates `manifest.json` files without calling
`read_json()`. It then registers the manifest even when `payload.json` has been
modified. `is_published()` checks file existence, not checksum/schema. A
focused repro changed the payload after publication; recovery registered it as
valid and reported no missing artifact.

The catalog publication table only receives `CATALOGED`; it never durably
records `STAGED`, `FILES_PUBLISHED`, failure, or retry state. Manifest parsing,
schema/version validation, invalid quality values, and malformed files can
abort application startup instead of being quarantined. Retention/tombstones
remain absent.

**Impact:** corrupt research data can become discoverable as valid, violating
the design's central artifact invariant.

**Required correction:** recovery must verify both files, canonical checksum,
manifest schema/version, category/ID path agreement, and upstream fields before
catalog registration. Quarantine invalid directories and record an auditable
failure. Persist a recoverable publication state before file publication, or
use an explicit file-first outbox protocol with proven crash-point tests.

### R-05 — SQLite connections are not deterministically closed

**Severity:** P1  
**Evidence:** stores repeatedly use `with sqlite3.connect(...) as connection`.
The SQLite connection context manager commits/rolls back but does **not** close
the connection. A focused temporary-directory run left `catalog.db` locked on
Windows during cleanup. This pattern occurs in jobs, catalog, ledger,
operations, and migrations.

**Impact:** file-handle accumulation, Windows backup/restore/delete failures,
and avoidable resource pressure in a long-running server.

**Required correction:** wrap connections with `contextlib.closing()` plus an
explicit transaction context, or expose one small connection/transaction
factory that always closes. Add a Windows-oriented test that repeatedly opens
stores and then renames/removes the database after GC-independent closure.

### R-06 — Ranking tie handling creates artificial alpha

**Severity:** P0  
**Evidence:** `rank_feature_values()` sorts by `(value, instrument_id)` and
uses the array index as percentile. Equal factor values therefore receive
different percentiles solely because of their identifier. A two-member equal
value repro assigned A=0 and B=100; `RankingSnapshot.create()` then gave them
different sequential ranks. Every factor is also implicitly “higher is
better”, and every row is marked eligible.

The design requires separate immutable percentile, score, and ranking
snapshots. The implementation takes an externally supplied `score_snapshot_id`
but computes percentiles and scores in memory without publishing those
artifacts or proving that the ID describes them.

**Impact:** rankings and portfolio choices can change because of ticker/ID
ordering, and lineage can claim a score artifact unrelated to the computation.

**Required correction:** define factor direction and an explicit tie policy
(for example average percentile plus dense/competition rank), eligibility and
missing-data rules, and deterministic rounding. Publish feature-set →
percentile → score → ranking as four validated artifacts and derive each ID
from the actual output. Add permutation, tie, single-member, missing, negative,
and duplicate-member properties.

### R-07 — Provider ingestion does not preserve raw evidence and can leak secrets

**Severity:** P1  
**Evidence:** `ingest_market_bars()` receives already normalized bars and writes
those bars into the artifact labelled `market/raw/<provider>`. It does not
store the provider response, response timestamp, request range, provider/API
version, timezone, adjustment metadata, counts, or validation results.

Redaction checks only top-level keys exactly equal to `token`, `secret`,
`password`, or `authorization`. A focused repro persisted both
`{"api_key": "LEAK2"}` and a nested token. Errors and job events have no shared
sanitizer. Retry/backoff/rate limiting and exchange-calendar checks are absent.

**Impact:** source data cannot be faithfully replayed, and credentials may be
written to immutable artifacts.

**Required correction:** introduce a provider response envelope and preserve
the original serializable response before normalization. Apply recursive,
allow-list-based redaction to request, response, exceptions, logs, and job
events. Record retrieval time, source version, interval, timezone, inclusive/
exclusive date semantics, adjustment basis, counts, and quality results.

### R-08 — Backtest output and metrics are incomplete

**Severity:** P1  
**Evidence:** the first equity point is recorded only after the first step and
`total_return` uses that point as starting equity, not initial portfolio value.
The runner does not use `portfolio_accounting`, fees, slippage, cash flows, or a
fill-model implementation. `SimulatedFill` lacks side, fees, currency, order/
decision correlation, and execution timestamp. The result packs all outputs
into one JSON artifact and bypasses `ArtifactPublisher`/catalog.

`BacktestRunManifest` validates neither required IDs/strings, date ordering,
input quality, output IDs/checksums, nor immutable code provenance. Callers can
supply any `code_revision` string.

**Impact:** reported performance and reproducibility are not trustworthy enough
for strategy selection.

**Required correction:** seed equity with initial marked value, model fills
through accounting, define cash-flow-aware metrics, validate the manifest, and
publish separately checksummed decisions/fills/equity/metrics/report through
the cataloged publisher. Capture code revision from the build/runtime, not
free-form request input.

### R-09 — The legacy implementation was removed before replacement parity

**Severity:** P1  
**Evidence:** the working tree deletes the legacy routes, services, models,
repositories, schemas, configuration, and provider adapters. `run.py` now
exposes only health and generic job endpoints. No registered handler performs
ingestion, screening/ranking, backtesting, portfolio actions, or paper
execution. Static/template files remain, but are not served by the new shell.

This conflicts with the design's additive-phase rule and with
`IMPLEMENTATION_PLAN.md`, which says to preserve the current UI/REST surface
until parity and to retire legacy code incrementally. `CURRENT_STATE.md` and
several other documents still describe the deleted architecture.

**Impact:** the product's primary user-visible capability is absent and there
is no executable old-vs-new parity oracle or reversible cutover path.

**Required correction:** either restore the legacy path behind read-only/
feature-flagged adapters until parity is signed off, or explicitly approve a
breaking rewrite and preserve a tagged read-only baseline plus migration
fixtures. Do not label legacy retirement complete until route, data, and golden
behavior reconciliation reports exist.

### R-10 — Point-in-time reference and market capability is mostly contractual

**Severity:** P1  
**Evidence:** alias, universe, calendar, and corporate-action dataclasses exist,
but only instruments and universes have publishers. There is no resolver by
effective/as-of date, broker-token history, benchmark/fundamental snapshot,
corporate-action snapshot, adjusted-bar computation, or availability policy.
`MarketDataSnapshot` itself has no invariant checks for provider, duplicate
instrument/date rows, ordering, requested range, or adjustment compatibility.

**Impact:** a historical run cannot prove the exact tradable universe, symbol/
token mapping, benchmark, or adjustment state it used.

**Required correction:** implement immutable snapshot publishers and
point-in-time resolvers for every required input. Add uniqueness/range/calendar
validation and make strategy capabilities block or qualify runs when inputs are
missing, stale, partial, or adjustment-pending.

### R-11 — “Frozen” revisions contain mutable mappings and weak validation

**Severity:** P1  
**Evidence:** frozen dataclasses store caller-owned dictionaries for revision
parameters, strategy weights, factor values, manifest parameters, and bars.
Some are copied but remain mutable; others retain the original mapping. A
revision can therefore change after creation while keeping the same revision
ID, and its definition hash can change over time. Semantic versions, duplicate
inputs/outputs/configuration IDs, finite weights, non-empty member IDs, and
cross-object compatibility are incompletely validated.

**Impact:** historical immutability and hash stability—the basis of replay—are
not guaranteed.

**Required correction:** canonicalize mappings to immutable representations,
deep-freeze nested values, validate finite decimals and unique/non-empty IDs,
and hash the complete canonical definition. Add mutation-attempt and hash-
stability tests.

### R-12 — Health, backup, and configuration evidence is misleading

**Severity:** P2  
**Evidence:** `sqlite_ready()` opens the supplied path read/write. For a missing
path it creates an empty database and returns `True`. Readiness checks only
`SELECT 1`, not schema versions, writer availability, artifact root, or failed
recovery. `Makefile` and README commands still reference
`instance/operations.db`, while composition uses `instance/system.db`.
Backups may target an existing destination; no integrity check or restore drill
is performed after copy.

**Impact:** operators can receive a green readiness signal for an unusable or
newly created store and can back up the wrong file.

**Required correction:** open readiness in SQLite read-only URI mode, require
the expected namespace versions/tables, and report recovery/catalog health.
Make backup destinations immutable/versioned, run `PRAGMA integrity_check`,
restore to a disposable location, and verify schema plus counts. Generate
paths from `RuntimeConfig` rather than duplicating filenames in docs/scripts.

### R-13 — CI and dependency reproducibility are not at the documented gate

**Severity:** P2  
**Evidence:** CI installs with `pip install -e '.[dev]'`, ignoring
`poetry.lock`, then runs Ruff. The present tree has 119 Ruff violations, so the
workflow is not green. CI omits coverage thresholds, formatting, type checks,
security/dependency scanning, package build, restore drill, and a Windows job.

The project requires Python >=3.13 while the local environment is 3.12.14. The
lock contains yfinance 1.3.0, but the broad `yfinance>=0.2` constraint and pip
installation produced 1.7.0. As of this review, PyPI reports Flask 3.1.3,
Waitress 3.0.2, and yfinance 1.7.0 as current releases:
[Flask](https://pypi.org/project/Flask/),
[Waitress](https://pypi.org/project/waitress/), and
[yfinance](https://pypi.org/project/yfinance/).

**Impact:** local, lock-based, and CI installations can validate different
dependency APIs; provider behavior may change without a reviewed lock update.

**Required correction:** choose one lock/install workflow and enforce it in
CI; test the declared Python version; constrain high-volatility provider
adapters to reviewed compatible ranges; add fixture-based contract tests before
dependency upgrades. Make lint/format/type/security/package/coverage checks
real release gates.

### R-14 — Several optimizations should wait; a few are safe now

**Severity:** P3  

Safe now:

- centralize SQLite connection creation, PRAGMAs, transaction handling, and
  closure;
- avoid setting `journal_mode=WAL` on every connection;
- batch artifact/catalog reads and add catalog indexes for lineage/status;
- replace long one-line expressions with named canonicalization/validation
  functions and run the configured formatter;
- use property-based tests for ranking permutations, accounting sequences, and
  state-machine transitions.

Defer until measurement:

- PostgreSQL, DuckDB, Parquet, distributed queues, microservices, and caching;
- large worker pools before lease/cancellation correctness and workload limits
  are defined;
- checkpoint projections before event-ledger replay is correct and measured.

This follows the target design: first establish correctness and reproducible
artifacts, then optimize from benchmark evidence.

## Required delivery order

1. **Stop release/cutover:** keep live execution disabled and do not treat
   current backtests, rankings, or paper reports as authoritative.
2. **Fix financial correctness:** R-01, R-03, R-06, and R-08 with golden and
   property tests.
3. **Fix durability:** R-02, R-04, and R-05 with crash, stale-worker,
   cancellation, corruption, and Windows file-lifecycle tests.
4. **Restore one vertical product slice:** point-in-time inputs → approved
   features → percentile → score → ranking → next-bar backtest artifact, all
   cataloged with immutable lineage.
5. **Choose and document migration posture:** additive compatibility path or an
   explicitly approved breaking rewrite; reconcile legacy data and behavior.
6. **Harden providers and operations:** recursive redaction, raw evidence,
   read-only readiness, verified restore, and real CI gates.
7. **Implement paper ledger lifecycle and reconciliation.** Only after an
   observation period and failure drills should a live-adapter design review
   begin.

## Minimum acceptance evidence for the next review

- Golden timing fixtures prove no close/intraday signal can fill at an earlier
  same-day open.
- Fill-model revisions demonstrably change fills/cash/metrics when fees or
  slippage change.
- Equal factor values receive the documented equal percentile/rank regardless
  of input order or instrument ID.
- A reused ledger/job idempotency key with a different canonical payload is
  rejected.
- A stale job owner cannot heartbeat, complete, fail, or overwrite the current
  owner's result; cancellation cannot finish as success.
- Recovery refuses or quarantines missing, malformed, or checksum-mismatched
  artifacts and never serves them as `VALID`.
- Repeated database operations leave the SQLite file immediately movable on
  Windows.
- Nested credentials and common secret aliases cannot enter artifacts, events,
  logs, or HTTP responses.
- The end-to-end vertical slice runs through a registered worker and produces
  cataloged manifests for every stage.
- CI passes on the declared Python version with tests, formatting, lint, type,
  coverage, security/dependency checks, package build, migration, and verified
  restore evidence.

## Positive foundations to preserve

- Pure portfolio and accounting functions provide a clean test seam.
- Domain packages avoid Flask, SQLAlchemy, broker SDKs, and legacy imports.
- Artifact writes use private staging and atomic directory publication.
- Namespaced migrations and the intentional failure test are a sound base.
- Job events are persisted per job and readable by cursor.
- The HTTP shell defaults to loopback, uses constant-time token comparison,
  caps request size, and makes network binding explicit.
- Live broker submission is explicitly rejected.

These foundations reduce the cost of the corrections above, but they are
scaffolding rather than proof of release readiness.
