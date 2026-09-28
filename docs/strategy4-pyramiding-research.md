# Strategy 4 pyramiding: evidence and next experiment

Status: **Deferred / pending.** Research date: 28 September 2026. Pyramiding is excluded from the initial Strategy 4 integration. This document preserves the experiment proposal for later and does not change the single-entry baseline.

## Findings from the existing rule

The current add rule requires a new filtered 50-session first-cross, a stop anchor above the entry price of every prior lot, and available cash. Each add competes with new entries in the same ADX/ADTV ranking and is sized as an independent investment with up to 1% nominal risk. There is no add-to-initial-position ratio.

On Nifty Total Market, 84 adds were executed. Median delay from initial entry was 28.5 market sessions, and the median rise from initial entry was 24.10%. Of these, 32 were worth less than 1% of portfolio equity and 14 bought only one share. The 83 closed add lots lost INR 19,603.11 after allocated fees; one add lot remains open. Whole-portfolio terminal equity was INR 23,220.37 higher with pyramiding enabled, despite the negative closed add-lot attribution, because the portfolios also differ in other investments. Drawdown increased from 28.67% to 30.13%.

Nifty 500 and the application NSE/BSE universe show similar median delays (29 and 32 sessions), approximately 25% prior appreciation, negative closed add-lot P&L, and lower terminal equity with adds. The evidence is mixed across universes. Delayed and small fills support testing earlier and more useful additions, but do not identify delay alone as a cause of lower returns: rank competition, cash constraints, concentration and subsequent reversals also matter. Total Market includes BSE histories for five BE rows with no stored NSE history; this coverage choice materially affects results.

A fresh first-cross can suppress adds throughout a persistent breakout: yesterday's close may already be above yesterday's Donchian upper band. This is a separate restriction from waiting for prior lots to reach nominal breakeven.

The stop anchor is a sizing reference, not an executable guaranteed breakeven stop. Actual exits occur on a close signal and execute at the next valid open. Overnight gaps and fees can produce losses even when the sizing calculation calls old risk zero.

Reproducible attribution: `tools/strategy4_pyramid_diagnostics.py`; result: `backtesting_results/strategy4_pyramid_diagnostics_20260928.json`. Closed add-lot attribution excludes open adds and displaced alternative investments. Whole-portfolio on/off comparisons capture the total portfolio effect.

## What the external evidence supports

Trading Blox's official Turtle documentation describes adding at 0.5 ATR price intervals measured from prior fills, volatility-based sizing, limits on units, and raising earlier stops as additions occur. This provides an established rule to test without waiting for all older lots to reach breakeven. Its performance cannot be assumed to transfer to NSE stocks or our daily next-open execution model.

Source: [Trading Blox: Turtle System Rules](https://www.tradingblox.com/docs/users-guide/17-built-in-systems-and-blox/turtle-system-rules/), sections Unit Add (ATR), Stop (ATR), and Entry Orders. The published implementation also retains a breakout-price floor for adds; a pure ATR continuation trigger would be our adaptation.

## Recommended experiment: ATR continuation with recycled risk

This is a proposed adaptation, not a published proven optimum. It changes the previously agreed zero-old-risk condition explicitly in a separate variant.

1. Keep initial entries, exits, 15-stock limit, costs, gap checks and shared ADX/ADTV ranking identical to the baseline.
2. For an existing holding, create an add candidate when the completed session's close reaches the last actual fill plus 1 ATR, measured using ATR fixed at that last fill's signal date. Retain ADX > 25, bullish Supertrend, close above Supertrend and ADTV > INR 10 crore. Do not require another first-cross.
3. Evaluate each candidate at the next valid open. Add at most once per stock per session; never infer multiple intraday fills from a daily bar. Require the open still to exceed the add threshold and remain above the stop anchor; preserve the 3% gap ceiling relative to the signal close.
4. Let `S = max(Supertrend, prior-20-session Donchian low)` from the signal close. Calculate conservative existing nominal downside as `R_existing = sum(shares_i * max(entry_price_i - S, 0))`. Do not offset a losing lot's risk with a profitable lot's unrealized gain.
5. Set available nominal risk to `max(0, 0.01 * equity_at_open - R_existing)`. Size the new investment as `floor(available_risk / (open - S))`, further limited by the existing 10% per-order cap, ADTV cap and cash including fees. This treats the add as a newly sized investment, without a position-size ratio.
6. Recompute risk at each proposed add; include every previous add in the existing-risk calculation. The 1% budget is shared by all lots in the stock at that moment, rather than granting another unrestricted 1% while old risk remains positive. Nominal risk can later rise if the anchor falls; this is not a guaranteed loss cap.
7. Continue to use the existing exit model for the first experiment. Any ratcheted stop or intraday hard-stop change must be a separate variant so its effect can be measured.

Do not add a cash reservation or minimum-order rule to the first experiment. Small fills are a measured issue, but changing cash allocation at the same time would confound the timing/risk comparison.

## How to test without selecting an overfit winner

Use four fixed arms: Off; current first-cross plus zero-old-risk; ATR continuation plus zero-old-risk (isolates trigger change); ATR continuation plus recycled aggregate risk (isolates risk change). Fix 1 ATR before testing. A 0.5 ATR sensitivity run has historical precedent but should not be selected merely because its full-period return is highest.

Use 2022–2023 for development, report 2024–2025 separately as previously viewed validation, and label 2026 as retrospective monitoring. All of these periods have already influenced discussion; none is a pristine holdout. Evaluate Nifty 500, Total Market and the application universe with identical policies.

Compare return, drawdown, concentration, turnover, fees, add delay, add notional, lot outcomes and portfolio-level incremental equity. Diagnose cash displacement explicitly. Promotion requires consistent evidence across periods and universes, followed by forward observation; an earlier trigger by itself is insufficient.

## Pending decision

No pyramiding variant is selected for implementation. Current pyramiding improved Total Market terminal equity with a deeper drawdown, and lowered terminal equity in the other two universes. Neither setting dominates consistently. Any future alternative remains unimplemented and unbacktested. The initial Strategy 4 implementation uses pyramiding Off.
