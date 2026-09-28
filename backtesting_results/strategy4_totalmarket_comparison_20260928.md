# Strategy 4: Total Market and universe comparison

Requested period: 1 January 2022 to 28 September 2026. Actual sessions: 3 January 2022 to 18 September 2026 (1,169 sessions). No later stored prices are available.

Settings: starting capital INR 500,000; maximum 15 distinct stocks; nominal risk 1% of current equity per order; order value cap 10% of equity; participation cap 1% of prior 30-session ADTV; 50 bps round-trip costs. Pyramiding retains the previously agreed zero-old-risk rule, independent sizing and shared ADX/ADTV ranking. Open holdings are marked to their latest stored close, not forcibly sold.

## Results

| Universe | Pyramiding | Final equity (INR) | Return | CAGR | Max drawdown | Adds |
|---|---|---:|---:|---:|---:|---:|
| Nifty 500 | Off | 1,155,228.66 | 131.05% | 19.45% | -29.25% | 0 |
| Nifty 500 | On | 1,061,512.05 | 112.30% | 17.32% | -24.37% | 75 |
| Nifty Total Market | Off | 930,180.16 | 86.04% | 14.08% | -28.67% | 0 |
| Nifty Total Market | On | 953,400.53 | 90.68% | 14.68% | -30.13% | 84 |
| App NSE + BSE, market cap >= 500 crore | Off | 620,641.96 | 24.13% | 4.69% | -38.04% | 0 |
| App NSE + BSE, market cap >= 500 crore | On | 593,880.21 | 18.78% | 3.72% | -40.55% | 89 |

## Annual returns

| Universe / mode | 2022 | 2023 | 2024 | 2025 | 2026 through 18 September |
|---|---:|---:|---:|---:|---:|
| Nifty 500 / Off | 5.08% | 81.88% | 19.82% | -15.53% | 19.43% |
| Nifty 500 / On | 0.22% | 86.90% | 12.46% | -8.70% | 10.38% |
| Nifty Total Market / Off | 1.04% | 64.91% | 27.47% | -10.76% | -1.84% |
| Nifty Total Market / On | 2.84% | 64.75% | 29.56% | -9.64% | -3.86% |
| App NSE + BSE, market cap >= 500 crore / Off | -13.65% | 38.05% | 10.84% | -21.74% | 20.05% |
| App NSE + BSE, market cap >= 500 crore / On | -15.76% | 43.95% | 17.07% | -22.09% | 7.40% |

## Total Market coverage

CSV rows included: 755 (750 EQ and 5 BE). Matched ISINs: 749; instruments with stored bars: 748. Five BE rows use BSE histories matched by identical ISIN because NSE histories are absent; the remaining matched rows use NSE. Missing ISINs: ['DU1560A01023', 'DU2560A01023', 'DUM256C01024', 'DUM510W01014', 'DUM545A01024', 'INE545A01024'].

No additional market-cap filter was applied to the Total Market CSV. The Nifty 500 comparison uses the earlier 500 EQ-member CSV, 498 matched. Membership is applied retrospectively; this is not a historical constituent backtest. The app universe additionally uses current market caps retrospectively.

## Pyramid diagnostics

| Universe | Median add delay from initial entry (sessions) | Median price rise from initial entry | Closed add-lot P&L (INR) | One-share adds | Adds below 1% equity |
|---|---:|---:|---:|---:|---:|
| Nifty 500 | 29 | 25.52% | -19,966.03 | 20/75 | 31/75 |
| Nifty Total Market | 28.5 | 24.10% | -19,603.11 | 14/84 | 32/84 |
| App NSE + BSE, market cap >= 500 crore | 32 | 24.74% | -42,628.72 | 12/89 | 35/89 |

Diagnostics show that executed adds arrive after substantial appreciation and many are small. This supports the concern about delayed and cash-limited additions, but does not establish which constraint causes the return reduction. Closed add-lot P&L excludes open adds and does not measure displaced new entries; compare whole-portfolio on/off results for the total effect.

The current rule requires both a new filtered 50-session first-cross and a stop anchor above every prior lot entry. A continuous breakout can fail the first-cross condition even while the trend remains strong. The stop anchor is a sizing reference: exits remain close signals followed by next-open sells, so nominal zero risk is not a guaranteed breakeven execution.

Pyramiding is deferred from implementation. For the initial Strategy 4 integration, use the Off configuration. The historical comparison is retained as research evidence: On increased Total Market terminal equity by INR 23,220.37 with a deeper drawdown, and reduced terminal equity on Nifty 500 and the application universe. Any future add-rule work remains pending; see docs/strategy4-integration-plan.md.

Verification: cash remained nonnegative, the stock count stayed at or below 15, and final equity reconciled to each equity curve. Nine Strategy 4 tests and Ruff passed. Corporate-action adjustments remain outside the agreed scope.

## Unmatched CSV rows

| Symbol | ISIN |
|---|---|
| DUMMYHEG | DUM545A01024 |
| DUMMYINGL1 | DU1560A01023 |
| DUMMYINGL2 | DU2560A01023 |
| DUMMYINXGN | DUM510W01014 |
| DUMMYTRVN | DUM256C01024 |
| HEGAM | INE545A01024 |
