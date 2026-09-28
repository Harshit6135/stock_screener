# Strategy 4 v4 implementation verification

Verified against `Positional Trend-Following Strategy for the Nifty 500 v4.md`, including its embedded mathematical formulas, and the subsequent user decisions: configurable portfolio limits, ₹5 lakh/15 stocks/1% risk defaults, absent stock bars treated as holidays, expanded experimental universes, and pyramiding deferred. Historical return illustrations and corporate actions are outside this verification scope.

## Rule trace

| v4 requirement | Implementation and finding |
| --- | --- |
| Nifty 500 constituents | Default daily signals and replay use the Nifty 500 CSV, EQ identities and NSE prices. Total Market and the ₹500 crore application universe are explicit research alternatives. |
| Current constituents applied retrospectively | Source membership hash and retrospective membership caveat are recorded. Point-in-time membership is unavailable. |
| Prior 30-session ADTV | Simple average of prior `close × volume` values; the signal bar is excluded. Eligibility is strictly greater than ₹100,000,000. |
| 100 valid prior bars | Default is 100 prior bars, so bar 101 is the first possible entry. The active `calculation.required_sessions` setting now reaches signals, held-stock evaluation and replay. |
| Missing stock bar | An absent record advances neither indicator state nor the stock's lookback count. Stored invalid OHLCV breaks the calculation segment. This reflects the later user instruction. |
| Wilder ATR(10) | Arithmetic mean seed of the first ten true ranges, followed by Wilder recurrence. Fixed-fixture values are verified. |
| Wilder ADX(14), strictly >25 | Directional movements and DX use Wilder smoothing; ADX is initialized from fourteen DX observations. Equality to the threshold rejects entry. |
| Donchian upper 50 / lower 20 | Uses prior highs/lows, excluding the current bar. Both bands are exposed in the feature artifact. |
| Bullish Supertrend seed | Seeds bullish on the first finite ATR. Both carried bands update before the current-band flip check. The recurrence matches the [TA-Lib documentation](https://ta-lib.org/functions/supertrend.html). |
| Strict Supertrend flip | Equality does not flip. Fixed OHLC fixtures verify the ATR, active line and bullish/bearish transition. |
| First cross | `previous close <= previous upper band` and `current close > current upper band`, after warm-up and liquidity eligibility. No continuously-above-band re-entry. |
| Momentum and volatility filters | First cross plus ADX strictly above threshold, bullish Supertrend and close strictly above its active line. |
| Deterministic ranking | Descending ADX, descending ADTV, alphabetical ticker. Fixtures verify each tie-break level. |
| Next-open execution | Replay and retrospective proposals use the following stored session's opening price. This is a modeled execution price, not proof of a live fill. |
| Initial anchor | Higher of signal-date Supertrend and prior 20-session low. |
| Gap filter | Open strictly above signal close ×1.03 rejects the entry. Exactly +3% is allowed. |
| Anchor filter | Open at or below the anchor rejects the entry. |
| Integer risk sizing | Floors equity × risk fraction / (open − anchor), then applies configurable order-value, ADTV and fee-aware cash caps. Fees reduce the equity available for later ranked orders. |
| ADTV participation | Default cap is 1% of signal-date prior ADTV; configurable as requested. |
| Whole-position trailing exit | Close strictly below Supertrend or Donchian low triggers liquidation at the next valid open. Exits precede competing entries. |
| Unavailable held-stock open | Last valid close supplies valuation. Exit remains pending, reconstructed from held-position history, including after universe removal. Other stocks can still be evaluated. |
| Re-entry | Requires a fresh first cross. Pyramiding remains disabled in application actions and replay. The old research CLI retains its explicit experimental switch. |
| Phase 1 arms | Baseline contains all eligible Donchian first-cross events; filtered arm is its subset. Both use the same gap/cost assumptions. Neither arm applies position sizing or the Supertrend anchor opening filter. |
| Fixed forward windows | 5, 20 and 50 sessions; 50 bps round-trip cost; MAE is a nonnegative loss magnitude. Incomplete windows are excluded. |
| Dependence-aware uncertainty | Calendar-session stationary bootstrap keeps same-day stock events and nested arm membership together. Default 5,000 replicates; mean block lengths 5/20/50; recorded seeds. |
| Advancement gate | Requires 30 complete primary events per arm/period, positive development interval, positive validation difference and no worse validation p90 MAE. Adequate bootstrap support is now checked for both periods; empty studies are inconclusive. |

## Corrections made during verification

1. Removed the hardcoded warm-up from application execution paths and read the active revision setting.
2. Exposed prior upper Donchian band, ATR and Supertrend direction for audit.
3. Corrected the Phase 1 bootstrap-support gate for the validation period and empty samples.
4. Aligned replay/CLI starting-capital defaults with the agreed ₹5 lakh configuration.
5. Prevented held-stock holidays from blocking proposals and retained unexecuted exits. Exact held exchange/instrument histories are read rather than substituted through ISIN preference.
6. Made opening-price and circuit-data assumptions explicit in proposal/backtest artifacts.

## Limits of the verification

- **Live market-on-open flow remains incomplete.** The current proposal path requires stored, completed action-date bars. It does not produce a pre-open intent or submit a live T+1 opening order. A model that filters on the observed opening price needs an execution contract for obtaining that price and submitting the order.
- **Unfillable upper-circuit skip is not implemented from actual fillability evidence.** Daily OHLCV does not provide order-book or circuit-band fillability. The code labels this limitation rather than inferring executable liquidity from daily volume.
- **Native TA-Lib output parity has not been run.** Formula review and deterministic fixtures pass, but TA-Lib is not installed. This does not fulfill the document's additional native-output parity requirement.
- **Research advancement is not an automatic backtest permission gate.** The user-authorized simulations can run as exploratory research. The saved `strategy4_event_study_20260927.json` says `does_not_meet_phase1_gate`, because validation p90 MAE was worse. That historical result has not been regenerated after the missing-bar change.

## Verification evidence

- `tests/test_strategy4_v4_contract.py`: fixed mathematical fixtures; warm-up, ADX/liquidity equality, gap/anchor boundaries, ranking, execution ordering and bootstrap-gate cases.
- `tests/test_strategy4_integration.py`: actual composed application flow from stored OHLCV through real features and signals, ledger-backed action proposals, and the cataloged replay; prices and quantities agree. Also covers a held BSE name outside the current universe with a pending exit across a missing open.
- Full suite: **274 passed**. Ruff and Python compilation passed for the implementation and the verification tests.

**Conclusion:** the core signal and portfolio simulation rules match v4 with the agreed overrides. Live opening execution, circuit fillability and native-output parity remain incomplete verification items; the saved research evidence has not passed the advancement gate.
