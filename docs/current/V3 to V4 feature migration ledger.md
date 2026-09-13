# V3 to V4 feature migration ledger

The source implementation is the clean `dead-code-cleanup` worktree at commit
`dabff59`. The target is the current v4 working tree. A domain class alone is
not counted as a migrated feature: the workflow needs storage, a callable API
or job, and an end-to-end result that can be queried.

| V3 capability and route family | V4 state at comparison | Migration target |
|---|---|---|
| Day-zero imports, Kite instrument sync (`init`, `instruments`) | NSE and BSE/Kite equity sync, dated token lookup and change-history APIs implemented; exclusion/source reconciliation audit pending | Versioned NSE/BSE/Kite snapshots, ISIN and token matching, query API |
| Historical OHLCV refresh and query (`marketdata`) | Per-symbol v3 read-only import, Kite fetch jobs, bar query and bounded coverage/latest-date API implemented; all-symbol scheduling and reconciliation pending | Durable fetch/backfill jobs, normalized bar storage, bounded query API |
| Index/Nifty 500 history and live index prices (`index`) | Eight tracked indices have 286 Kite daily bars each and a timestamped quote job/API; v3's continuous start/stop polling lifecycle remains pending | Dated index tokens and history, freshness-labelled quote API |
| Corporate-action repair | Contract only | Action facts, adjusted revisions and dependent-artifact invalidation |
| Strategy 1 and 2 indicator computation/query (`indicators`) | Both formula ports and feature artifacts implemented; direct symbol/date/latest feature query, controlled patch job, Strategy 2 quality/turnover limitations and ADX parity review pending | Versioned formula implementations, warm-up and query API |
| Daily factor percentiles (`percentile`) | Both strategies published and read back for ten sessions | Both legacy factor sets with published daily snapshots |
| Daily composite scores/penalties (`score`) | Both strategies published; zero-volume/flat-OHLC exclusions added; parity and candidate-set review pending | Both strategies' exact penalties and exclusions |
| Weekly rankings/query/top N (`ranking`) | Both strategies' Mon–Fri averages and top-N API exercised for two weeks; symbol/history/close read model and tie/candidate parity review pending | Mon–Fri aggregation, tie policy, query and top-N APIs |
| Strategy/config management (`config`) | Immutable full-schema draft revisions, operator approval, effective-date resolution and read APIs implemented; active revision drives paper-action and backtest policy; research revision selection and v3 config import pending | CRUD lifecycle, validation, approval and effective dates |
| Pipeline/recalculation/progress (`app`) | Durable dated research-pipeline parent and ordered daily/Friday-ranking child jobs with status readback implemented; market/reference orchestration, calendar ranges, explicit stage retry and cancellation propagation pending | Typed stage and full-pipeline jobs with resume/cancel |
| Action generation/approval/process (`actions`) | Durable paper proposal job and operator review/process/event APIs exercised against copied live ranking and bar data; v3 per-item edits, manual action intents, sell-before-buy/open-price cash re-sizing, cash-constrained pending buys, midweek close-stop/vacancy and 5% stale-buy rules, trailing stops and live execution parity pending | Persisted action lifecycle and operator APIs |
| Broker order submission, status and fill reconciliation (v4 enhancement) | Deliberately not implemented: V4 is paper-only. Isolated portfolio credentials exist but are not injected into execution. | Feature-gated Kite execution gateway, idempotent order/fill event log, status reconciliation, FIFO posting and conflict-safe manual-fill fallback |
| Holdings, capital, manual trades, journal, live prices (`investment`) | Operator-protected paper account/direct manual-fill, FIFO holdings/cash/P&L/event APIs exercised; guarded v3 snapshot preview/import is implemented; reviewable manual trade intents, cash transfers, journal, valuation/live prices, XIRR, stop-based risk and historical realised-P&L parity pending | Event-backed commands, projections and APIs |
| Backtest run/history/report (`backtest`) | Paper-only job, cataloged report and list/detail APIs exercised for both strategies over five sessions; costs, corporate actions, long-history parity, v3 annual/trade/open-position report sections and named performance metrics pending | Executable backtest job, persisted run and report APIs |
| Dashboard and other v3 pages | Minimal `/app` page now shows rankings, index quotes, job lookup, paper-account readback and paper-action review/process controls; v3 pipeline, portfolio, config and backtest workflows/pages are pending | Minimal v4 pages for ranked stocks, jobs, actions and portfolio |
| Daily Kite authorization | Implemented, local only | Verify configured redirect URL and refresh UX |

The active delivery order is reference and market data, indicators, factor
percentiles, daily scores, weekly rankings, then actions/portfolio/backtests
and the minimal interface. Each row stays open until a live or representative
end-to-end run proves its output can be read back from v4.

## Strategy 1 parity findings

A comparison of 60 symbols on 17 July 2026 against v3's stored factors found
median absolute differences of 0.000 for trend, efficiency and volume, 1.311
for momentum, and 17.148 for structure. The momentum difference includes
stale v3 indicator rows: for several symbols the stored 3- and 6-month
momentum does not equal the same v3 formula recomputed from its current
`market_data` rows. V4 recalculates from the immutable input bars.

V3's structure factor calls `pct_change(5)` on a one-date cross-sectional
DataFrame. That compares one stock's Bollinger bandwidth with a different
stock five rows earlier, making its result dependent on row ordering. V4 uses
the same stock's five-session bandwidth change. This is an intentional
behavioral correction and the resulting ranking delta must be reviewed before
release. A representative RELIANCE row had v3 structure 40.832 versus v4
61.091, while trend, efficiency, volume and the hard penalty matched closely.

## Live migration checkpoint, 12 September 2026

The v4 store contains a read-only v3 warm-up import plus current Kite bars for
1,376 matched symbols. The last ten completed sessions (31 August to
11 September) were recomputed with corrected Strategy 1 formula revision
`strategy1-v4-port-2`; 1,326 to 1,336 symbols were scored per day. Both
completed weeks were reranked, with 1,331 and 1,336 members. HTTP readback
verified every feature, percentile, score and ranking artifact and confirmed
the corrected artifacts are `VALID` in the catalog. One M&MFIN import failure
was repaired before the final run. The earlier formula-revision artifacts
remain immutable and superseded, not silently overwritten.

The NIFTY 500 benchmark has 286 Kite daily bars in the same v4 market store.
No active v4 job uses yfinance: v3 used it for market-cap enrichment and a
NIFTY 500 fallback. V4's liquidity policy is based on traded turnover, and
the unused yfinance adapter and direct dependency have been removed. Strategy
2 cannot be declared fully validated merely from benchmark availability: v3's
`quality_z_score` is a constant-zero placeholder, while its so-called
`scaled_turnover` is actually volume divided by its 20-day average, not a
float-turnover or market-cap measure. A versioned port is exposed as
provisional; its economic meaning and numerical parity still need review.

## Subsequent live checkpoint

NSE and BSE sync matched 1,974 and 4,906 Kite identities respectively. Seven
additional indices (NIFTY 50, NIFTY 100, NIFTY BANK, NIFTY MIDCAP 50, INDIA
VIX, SENSEX, BANKEX) each have 286 daily Kite bars. The timestamped index
quote snapshot returned eight prices and all eight were fresh at readback.
The quote job is operator-triggered; the old continuous start/stop ticker is
not yet migrated.

Strategy 2 revision `strategy2-v4-port-1` scored 1,290–1,295 stocks on the
same ten sessions and ranked 1,294 and 1,295 stocks for the two completed
weeks. All 30 daily Strategy 2 artifacts and both ranking artifacts passed
HTTP and catalog readback. These are *provisional* rankings: the inherited
quality input is an explicit constant-zero placeholder, and v3's mislabeled
scaled-turnover formula is retained as a documented relative-volume proxy.
The port additionally computes Bollinger change per stock rather than across
different stocks. None of this constitutes verified economic efficacy or
perfect v3 numerical parity.

An isolated paper-account smoke run exercised account creation, buy and sell
fills, FIFO cash/realised-P&L/remaining-lot projections and event readback
through the v4 HTTP routes. The ledger now rejects overdrafts and oversells
inside its write transaction, before any event is appended. This does not
yet migrate v3 holdings or action approval/processing.

The v4 `backtest.run` job replayed the 7–11 September completed week using
rankings from the prior Friday only, producing six Strategy 1 and five Strategy
2 simulated fills. Both reports and run-list APIs read back successfully.
Missing top-ranked candidate bars now fail the replay rather than silently
substituting another stock. Reports carry immutable source/revision lineage,
a source-code hash, and `PARTIAL` quality because corporate-action adjustment,
cost calibration and broader historical parity are still pending.

The new `actions.generate-paper-proposal` job uses a completed prior weekly
ranking and completed action-date bars. It publishes a `PARTIAL` immutable
proposal, then maintains a review/process SQL projection and append-only
proposal events. Approval does not trade; processing is explicitly paper-only,
version-checked and idempotent through the FIFO ledger. Multi-lot holdings are
aggregated for decision evaluation, while the original FIFO lots remain in the
ledger. A crash after artifact publication can reconstruct the proposal SQL
projection, and a crash after ledger commit can retry with the same command
key. Stale accounts and invalidated proposal artifacts are refused.

An isolated run copied the top three Strategy 1 stocks from the stored
4 September ranking and their 7 September bars. The job produced three BUY
decisions; approve/process via the HTTP adapter yielded three ledger fills,
three open lots, and GENERATED/APPROVED/PROCESSED proposal events. This was a
historical paper replay using completed bars, not a forward-trading or broker
order test. The fixed 10% FIFO-cost stop, absent v3 per-item edits and manual
account import, midweek close-based stop checks, and lack of corporate-action-adjusted bars mean this is not
yet v3 action parity.

Strategy configuration revisions now preserve the legacy portfolio-risk schema
(capital, risk, positions, concentration, exit, buffer and stop parameters)
in immutable configuration artifacts. A revision starts as a DRAFT, requires
an operator-approved effective date, and cannot be edited in place or share an
effective date with another approved revision for the same strategy. An active
revision now supplies the paper action position count, exit threshold,
concentration ceiling and swap buffer; its artifact is direct proposal
lineage. Until a configuration is approved, legacy-compatible action and
backtest requests continue to require explicit position sizing inputs. The
backtest also records the active configuration in report lineage. Research
jobs do not yet select these revisions, and v3 configuration import remains
open.

The v3 personal-database importer now opens its source SQLite file read-only,
requires a preview and exact symbol reconciliation, and imports a selected
holding snapshot only into a new account. It restores available cash and open
holding cost bases through normal ledger fills, records the source digest in a
`PARTIAL` immutable import artifact, and refuses partial imports. The live
preview of `instance/personal.db` found the 12 July 2026 snapshot had ten
holdings, all resolvable (including BSE fallbacks), ₹47,349.45 remaining cash
and ₹329,888.86 open cost basis. V3 does not retain sufficient individual sell
events to reproduce historical FIFO realised P&L, so that history is explicitly
not invented by this migration.
# V4 credential isolation enhancement

Market-data Kite credentials and daily access tokens are deliberately separate
from portfolio credentials. The market-data profile may be a shared team
profile; the portfolio profile never falls back to it, and is not injected into
market jobs or the paper-only execution gateway. Portfolio credentials are
deployment-local until V4 adds authenticated, encrypted per-user credential
storage.
