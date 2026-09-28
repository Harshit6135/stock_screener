# Strategy 4: ₹5 lakh, 15 stocks, 1% risk, ranked pyramiding

Requested period: 2022-01-01 to 2026-09-27. The first available session is 2022-01-03 and the last stored session is **2026-09-18**. Both runs use the same bars, signals, 50 bps assumed round-trip cost, and portfolio settings except for pyramiding.

```powershell
.\.venv\Scripts\python.exe tools/strategy4_backtest.py --start-date 2022-01-01 --end-date 2026-09-27 --initial-capital 500000 --max-positions 15 --risk-pct 1 --max-name-pct 10 --enable-pyramiding --output backtesting_results/strategy4_portfolio_5l_pyramid_20220101_20260927.json
```

For comparison, omit `--enable-pyramiding` and write to `backtesting_results/strategy4_portfolio_5l_no_pyramid_20220101_20260927.json`.

| Measure through 2026-09-18 | Pyramiding on | Pyramiding off |
|---|---:|---:|
| Starting capital | ₹5,00,000 | ₹5,00,000 |
| Ending marked equity | **₹10,61,512.05** | ₹11,55,228.66 |
| Total return | **112.30%** | 131.05% |
| CAGR | **17.32%** | 19.45% |
| Maximum drawdown | **−24.37%** | −29.25% |
| Closed trades | 402 | 404 |
| Pyramid add fills | **75** | 0 |
| Open positions at cutoff | 14 | 15 |
| Win rate on closed trades | 39.80% | 40.84% |
| Profit factor | 1.49 | 1.56 |
| Modeled entry and exit costs | ₹1,04,925.71 | ₹1,07,091.91 |

| Year | Pyramiding on | Pyramiding off |
|---|---:|---:|
| 2022 | +0.22% | +5.08% |
| 2023 | +86.90% | +81.88% |
| 2024 | +12.46% | +19.82% |
| 2025 | −8.70% | −15.53% |
| 2026 through 18 September | +10.38% | +19.43% |

## Pyramiding rule used

At each close, a new filtered 50-session first-cross signal is queued for the next open. Exits execute first. Signals for held and unheld stocks then share **one ranking**: ADX descending, 30-session average traded value descending, symbol ascending. Thus an add has no priority over a new stock.

For a held stock, the new signal-day stop anchor must exceed **every existing fill price**. This makes the old lots' price-to-anchor nominal downside zero before an add is considered. The add must also pass the same next-open gap and stop checks as a new entry. The new order is sized independently at 1% of opening equity divided by its own open-to-anchor distance, subject to the same **10% opening-equity order cap**, 1% of average traded value, and available cash. There is no add fraction, ratio to the previous holding, fixed add count, or aggregate stock weight cap. The 15-stock limit counts distinct names.

The recorded fills have a maximum **9.9991% order weight** and **0.99997% nominal risk per new order**. Combined stock weight reached **25.99%** after adds. Cash stayed nonnegative and the portfolio held at most 15 names. These checks concern planned nominal risk at the signal anchor; a next-open exit gap and transaction costs can cause larger realized losses.

**Result:** Pyramiding added 75 fills. Ending equity was ₹93,716.61 lower than the no-pyramid run, while maximum drawdown was 4.88 percentage points smaller. This is one exploratory historical comparison. The earlier fixed-horizon event-study validation gate failed.

The NIFTY 500 price index returned 50.22% over the same stored dates; it excludes dividends and trading costs. Current Nifty 500 constituents are applied to past dates, causing survivorship bias. Per research scope, stored OHLCV is used without corporate-action adjustment. Daily bars cannot verify upper-circuit fills or actual next-open slippage. Open positions at the cutoff are marked to market, not liquidated.
