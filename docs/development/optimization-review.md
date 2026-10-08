# Optimization review — 7 October 2026

This pass addresses the reviewed loading, duplication, and calculation hotspots
with focused changes. Existing accounting calculations, proposal decisions,
execution approval checks, and immutable artifact checksum validation remain the
basis for the results.

## Completed work, by priority

| Priority | Issue | Change | Validation |
|---|---|---|---|
| High | Holdings waited for charts, journal, and rankings | Page sections load and render independently, retaining account/generation checks and section-specific errors. | Browser tests hold secondary requests pending, reject them, and change the selected account. |
| High | Page revisits rebuilt valuation and history | An eight-entry process-local cache reuses results until source databases change. Account, date, risk inputs, broker snapshot, and the current India date distinguish relevant requests. | Cache-hit, market correction, cash transfer, provenance correction, changing risk inputs, separate accounts/dates, and response-copy tests. |
| High | History queried and replayed the ledger for every date | Batch dated projections read one consistent ledger snapshot and reuse the projection on dates without event changes. Missing-price exclusion still uses the same accounting projector. | Accounting/history regressions, connection/replay counting, and exact output comparison with the original implementation. |
| High | Research snapshot reads decompressed unrelated artifacts | Query category manifest metadata first and verify candidate payloads from newest to oldest. The existing verified `manifests()` contract remains unchanged. | Payload-read counting, corruption fallback, explicit date filtering, and artifact/research tests. |
| High | Valuation mixed HTTP and calculation responsibilities | Move valuation to a workflow function and reuse instrument/bar lookups across execution lots and event lists within the calculation. | Holdings grouping, totals, returns, taxes, stops, history, and read-count tests. |
| High | Action generation combined validation, loading, filtering, evaluation, and publication | Extract reference loaders and split generation into request-scoped stages with a short coordinator. Preserve validation order, sizing rules, errors, decisions, and source lineage. | Proposal, execution, managed-risk, security, and stop-sell tests; exact proposal/risk output or error comparison against the previous implementation across 16 scenarios. |
| Medium | Three legacy browser scripts duplicated active workspace scripts | Remove unreferenced `backtest.js`, `pipeline.js`, and `portfolio.js`; templates already use workspace versions. | Tracked-reference search, dashboard tests, browser loading tests, and active-script syntax checks. |
| Medium | Coverage validation and SQL were duplicated | Share the coverage-window reader; keep coverage and missing-range result algorithms separate. | Market history, fetch jobs, and positional replay input tests. |
| Medium | Latest saved ATR-stop selection was duplicated | Share dated stop selection between valuation and stop sells. | Portfolio stop and execution tests. |
| Medium | Live sorting repeatedly scanned rankings and recalculated keys | Index rankings once and calculate one sort key per displayed holding. | First-match precedence, missing-rank ordering, and one-key-per-row browser tests. |
| Low | ADTV repeatedly summed rolling windows; an unused ATR array was calculated | Use prefix differences only when non-negative integral values and a total at most 2**53 guarantee identical floating-point sums. Retain original summation for all other inputs. Remove the unused array and recurrence. | Bit-for-bit rolling values, numeric limits, fractional/non-finite fallbacks, adjacent liquidity thresholds, full feature outputs, and replay comparisons. |

## Cache behavior

The cache watches SQLite `PRAGMA data_version` on persistent read-only
connections. Any committed source-database write invalidates cached results,
including corrections that leave row counts and account versions unchanged.
This deliberately invalidates more often than a table-specific revision scheme.
No schema migration or persistent cache files are introduced.

Calculations run outside the cache lock, so history cannot block valuation.
Results computed during a source write are not retained. Failures are not
cached, and returned values are copied before response-specific decoration.
Broker and risk inputs are read for the request and included in its key.
Separate worker processes maintain separate caches and each observes database
writes independently. Cold requests still calculate their results.

## Validation and measurements

- Full Python suite: **625 passed**.
- Browser regression tests: **3 passed** with
  `node --test tests/browser/portfolio_loading.test.cjs`.
- Scoped Ruff checks and `git diff --check` passed. The seven Ruff findings
  present before this pass remain outside the focused fixes.
- Isolated fixture: 500 observed sessions, 20 fills, one instrument. Original
  history and optimized history returned identical dictionaries.

| Measurement | Time |
|---|---:|
| Original history reconstruction | 1,432.67 ms |
| Optimized history reconstruction | 33.81 ms |
| Valuation endpoint, cold | 49.59 ms |
| Valuation endpoint, cached | 0.83 ms |
| History endpoint, cold | 31.51 ms |
| History endpoint, cached | 2.75 ms |

These are local fixture measurements, not timings against the user's live
portfolio database. No broker calls or live database writes were used for the
benchmark.

For 10,000 synthetic integral-value bars, complete feature calculation returned
identical dictionaries with both ADTV implementations. Median times over seven
runs were 50.94 ms before and 45.33 ms after for the default 30-session window;
the 250-session window measured 70.31 ms before and 60.96 ms after. These are
local measurements of the certified fast path. Fractional and oversized inputs
retain the original calculation rather than changing precision to gain speed.

## Changes deliberately excluded

Broad rewrites of the accounting projector, action sizing rules, backtest
execution, research rebuilding, and indicator dispatcher remain outside this
surgical pass. Action generation now has separate stages without replacing its
domain rules, and ADTV uses its faster path only where numerical equivalence can
be certified.
