# Strategy 4 v4 event study — 2026-09-27

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe tools/strategy4_event_study.py --output backtesting_results/strategy4_event_study_20260927.json
```

The companion JSON includes the 11,268 raw baseline events, execution statuses, all complete event outcomes, bootstrap settings, and data coverage. The run uses the current Nifty 500 EQ constituent CSV retrospectively. Of its 500 ISINs, 498 match NSE reference instruments with bars. The two missing ISINs are `DUM545A01024` (DUMMYHEG) and `INE545A01024` (HEGAM). There are 628,159 stock bars in the loaded 2021-01-01 to 2026-09-18 range.

| Signal period | Complete 20-session events (filtered / baseline) | Filtered mean net | Baseline mean net | Difference | Block-bootstrap 95% interval for difference | Filtered / baseline p90 MAE |
|---|---:|---:|---:|---:|---:|---:|
| 2022–2023 development | 3,728 / 5,535 | 2.927% | 2.334% | +0.593 pp | +0.276 to +0.973 pp | 13.505% / 13.670% |
| 2024–2025 previously viewed | 3,077 / 5,489 | 1.086% | 1.077% | +0.009 pp | −0.523 to +0.450 pp | 16.101% / 15.833% |

The predeclared Phase 1 gate **does not pass**. Development clears its positive-difference interval. The previously viewed period has a negligible mean advantage and a worse 90th-percentile 20-session adverse excursion. The validation interval spans zero. The annual 20-session mean net return is 1.949% filtered versus 1.795% baseline in 2024, and −0.237% filtered versus +0.140% baseline in 2025.

Both arms use the same current-member universe, prior 30-session average `close × volume` above ₹100 million, first cross of the prior 50-session high, next-open modeled entry, gap skip above 3%, and assumed 50 bps round-trip cost. The filtered arm additionally requires ADX(14) above 25 and a bullish Supertrend(10,3) with the close above its line. Returns exit at the close of the fifth, twentieth, or fiftieth session; they are **event outcomes, not portfolio returns**. The event study omits portfolio sizing and the strategy-specific opening-price-versus-stop filter as specified for Phase 1.

The 20-session difference interval resamples calendar signal sessions in stationary blocks of mean length 20, moving all same-day events and their filtered/baseline membership together. It uses 5,000 replicates with recorded seeds. The 5- and 50-session horizons are secondary. This uncertainty estimate is exploratory in the short, historically viewed windows; it is not evidence of a blind out-of-sample edge.

Daily OHLCV cannot establish upper-circuit order fills, so eligible next opens are modeled fills. Historical index membership is unavailable; current members applied to past dates introduce survivorship bias. Per research scope, this run uses the stored price/volume series without corporate-action adjustment. These limitations can change measured outcomes. No Phase 2 portfolio simulation was run because the Phase 1 gate failed.
