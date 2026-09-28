# Strategy 4: Nifty 500 versus the ₹500 crore application universe

Run date: 2026-09-28. Requested period: 2022-01-01 to 2026-09-28. Actual stored sessions: **2022-01-03 through 2026-09-18**, 1,169 sessions. These are marked portfolio values, not forced liquidation proceeds.

The application universe snapshot is dated **2026-09-19** and contains **1,851 stocks: 1,631 NSE and 220 BSE-only stocks**, with recorded market capitalization at least ₹500 crore. Every member has stored bars in the loader's 2021-onward range, although daily signal eligibility still requires sufficient consecutive valid bars and ADTV > ₹10 crore. The snapshot is applied retrospectively; this is not a historical daily market-cap screen and has survivorship and market-cap look-ahead bias.

All runs use ₹5 lakh initial capital, at most 15 names, 1% nominal risk per new order, a 10% equity order cap, 1% ADTV participation, no leverage, and 50 bps modeled round-trip cost. The rules, exit timing, and pyramiding eligibility match the preceding Strategy 4 run. The broader run uses the Nifty 500 stored session calendar for comparability, while stock prices come from each member's recorded NSE or BSE series.

| Measure | ₹500 crore universe, pyramiding on | Nifty 500, pyramiding on | ₹500 crore universe, pyramiding off | Nifty 500, pyramiding off |
|---|---:|---:|---:|---:|
| Ending marked equity | **₹5,93,880.21** | ₹10,61,512.05 | ₹6,20,641.96 | ₹11,55,228.66 |
| Total return | **18.78%** | 112.30% | 24.13% | 131.05% |
| CAGR | **3.72%** | 17.32% | 4.69% | 19.45% |
| Maximum drawdown | **−40.55%** | −24.37% | −38.04% | −29.25% |
| Closed trades | 454 | 402 | 455 | 404 |
| Pyramid add fills | 89 | 75 | 0 | 0 |
| Closed-trade win rate | 32.60% | 39.80% | 35.60% | 40.84% |
| Open positions at cutoff | 15 | 14 | 15 | 15 |

## Yearly equity changes

| Year | ₹500 crore universe, pyramiding on | Nifty 500, pyramiding on | ₹500 crore universe, pyramiding off |
|---|---:|---:|---:|
| 2022 | −15.76% | +0.22% | −13.65% |
| 2023 | +43.95% | +86.90% | +38.05% |
| 2024 | +17.07% | +12.46% | +10.84% |
| 2025 | −22.09% | −8.70% | −21.74% |
| 2026 through 18 September | +7.40% | +10.38% | +20.05% |

| Year | Broad-universe pyramiding gain/loss | Year-end marked equity |
|---|---:|---:|
| 2022 | −₹78,819.29 | ₹4,21,180.71 |
| 2023 | +₹1,85,096.61 | ₹6,06,277.32 |
| 2024 | +₹1,03,486.34 | ₹7,09,763.66 |
| 2025 | −₹1,56,806.45 | ₹5,52,957.21 |
| 2026 through 18 September | +₹40,923.00 | ₹5,93,880.21 |

## Interpretation and checks

The broad-universe pyramiding run ended ₹4,67,631.83 below the Nifty 500 pyramiding run, with maximum drawdown larger by 16.18 percentage points. Turning pyramiding off within the broad universe increased ending equity by ₹26,761.74. The Nifty 500 price index returned 50.22% over the same stored dates, excluding dividends and trading costs. This historical comparison does not establish the cause of the difference or demonstrate a reliable trading edge.

The main run bought or added 388 distinct stocks, with 549 NSE and 9 BSE buy/add fills. Cash stayed nonnegative, names never exceeded 15, maximum new-order nominal risk was 0.99991%, and maximum order weight was 9.99504% of opening equity. Combined stock weight after adds reached 25.86%; each add was sized independently after the anchor exceeded all prior buy prices. Final cash was ₹6,314.19; the remaining ₹5,87,566.02 was the marked value of 15 open positions.

The previous Nifty 500 event-study gate failed. The broader universe has not had a separate event-study validation here. Stored bars are used without corporate-action adjustments as requested. Daily bars cannot establish upper-circuit fill availability or actual next-open slippage. Missing held-stock bars retain the last observed close for valuation.

## Reproduce and inspect

```powershell
.\.venv\Scripts\python.exe tools/strategy4_backtest.py --universe-source mcap500 --start-date 2022-01-01 --end-date 2026-09-28 --initial-capital 500000 --max-positions 15 --risk-pct 1 --enable-pyramiding --output backtesting_results/strategy4_mcap500_5l_pyramid_20220101_20260928.json
```

Omit `--enable-pyramiding` for the control. Complete fills, holdings, coverage, skips, and daily equity are in:

- `strategy4_mcap500_5l_pyramid_20220101_20260928.json`
- `strategy4_mcap500_5l_no_pyramid_20220101_20260928.json`
- The preceding Nifty 500 run files retain their `20260927` filenames; their last stored session is the same 2026-09-18.
