# Strategy 3 v4 portfolio backtest: ₹5 lakh and 15 stocks

Requested period: 2022-01-01 to 2026-09-27. First simulated session: 2022-01-03. Latest stored session: **2026-09-18**. Full fill ledger and daily equity are in `strategy3_portfolio_5l_15stocks_20220101_20260927.json`.

```powershell
.\.venv\Scripts\python.exe tools/strategy3_portfolio_backtest.py --start-date 2022-01-01 --end-date 2026-09-27 --initial-capital 500000 --max-positions 15 --holding-sessions 20 --output backtesting_results/strategy3_portfolio_5l_15stocks_20220101_20260927.json
```

| Measure | Result |
|---|---:|
| Starting capital | ₹5,00,000.00 |
| Ending marked equity | **₹4,52,235.39** |
| Total return | **−9.55%** |
| CAGR | **−2.11%** |
| Maximum drawdown | **−29.60%** |
| Closed trades | 501 |
| Win rate on closed trades | 44.91% |
| Profit factor | 0.94 |
| Open positions at cutoff | 10 |
| Cash at cutoff | ₹97,602.49 |
| Marked value of open shares | ₹3,54,632.90 |
| Modeled transaction fees | ₹1,00,880.64 |

| Year | Year-end equity | Gain/loss that year | Return |
|---|---:|---:|---:|
| 2022 | ₹4,88,719.46 | −₹11,280.54 | −2.26% |
| 2023 | ₹5,15,083.95 | +₹26,364.49 | +5.39% |
| 2024 | ₹5,26,589.68 | +₹11,505.73 | +2.23% |
| 2025 | ₹4,46,940.11 | −₹79,649.57 | −15.13% |
| 2026 through 18 September | ₹4,52,235.39 | +₹5,295.28 | +1.18% |

## Rules and interpretation

The run computes Strategy 3 v4 indicators across the current Nifty 500 EQ universe and the Nifty 500 benchmark. Qualifying signals use the v4 residual-score top quintile, prior-session Bollinger squeeze, prior low-volume proxy, Bollinger upper-band cross, current relative-volume threshold, and ₹10 crore prior-30-session traded-value screen. Candidates rank by residual score. A buy is modeled at the next open if the gap is no more than 3% and the open is above the signal-day Bollinger lower-band stop.

Each order is limited by 1% nominal equity risk to that fixed stop, 10% equity order value, 1% of average traded value, and cash. At most 15 names are held. This run does **not** pyramid. A held position exits at its fixed stop if a later open gaps below it or a daily low touches it. An unstopped position exits at the close of its **20th holding session**, matching the event study's primary horizon. This 20-session portfolio exit is an explicit modeling assumption because Strategy 3 v4 defined event outcomes rather than a complete shared-capital exit policy.

The 642 raw signals produced 511 buys; 501 positions closed and 10 remained open. Of the exits, 354 were horizon exits, 135 intraday stops, and 12 opening-gap stops. Cash never fell below zero; holdings never exceeded 15 names. The largest new-order weight was 9.9981% and largest nominal stop risk was 0.99997% of opening equity.

The v4 event-study validation gate **failed in both 2024 and 2025**. This backtest is exploratory and does not overturn that finding. Current Nifty 500 constituents were applied backward, so the test has survivorship bias. Stored bars were used without split/bonus adjustment; the existing corporate-action fact store contains no facts. Daily OHLCV cannot confirm intraday stop execution quality or upper-circuit fill availability. The 10 open positions are marked at 2026-09-18 closes and have not been sold. The Nifty 500 price index gained 50.22% over the same stored start and end dates, without dividends or trading costs.
