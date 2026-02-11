# Deferred Implementation Items

These items were identified during the spec audit but deferred from the current implementation cycle. Each section is self-contained and can be used as input for implementation when ready.

---

## 1. Adaptive Rebalancing (Spec Section 2.6)

**Spec Requirement:** Adjust rebalance frequency based on market regime instead of fixed weekly.

**Regime Detection Logic:**
```
Trending Market   → Weekly rebalance (capture momentum quickly)
Choppy/Sideways   → Bi-weekly (reduce whipsaws and costs)
Downtrend         → Monthly (minimize activity, preserve capital)
```

**Implementation Approach:**
1. **Nifty 50 data feed** — Fetch Nifty 50 index data (daily close) via Kite API or NSE website
2. **Trend Efficiency Ratio** — `TER = abs(close - close_20d_ago) / sum(abs(daily_changes_20d))`
   - TER > 0.6 → Trending
   - TER 0.3-0.6 → Choppy
   - TER < 0.3 → No trend
3. **EMA 50/200 crossover on Nifty** — Above both = trending, below 200 = downtrend
4. **New config class** — `RebalancingConfig` with thresholds and frequency mappings
5. **Integration point** — `ActionsService.generate_actions()` checks market regime before executing

**Files to create/modify:**
- `src/services/market_regime_service.py` [NEW] — Regime detection
- `config/strategies_config.py` [MODIFY] — Add `RebalancingConfig`
- `src/services/actions_service.py` [MODIFY] — Check regime before rebalancing
- `src/backtesting/runner.py` [MODIFY] — Dynamic week skipping based on regime

**Data needed:** Nifty 50 daily OHLCV data in `market_data` table or separate index table.

---

## 2. Correlation Clustering (Spec Section 2.5, Control 3)

**Spec Requirement:** Limit correlated positions to avoid concentration in correlated stocks.

**Implementation Approach:**
1. Calculate rolling 60-day returns correlation matrix for all held positions
2. Cluster stocks with correlation > 0.7 into groups
3. Limit allocation per cluster to 30% of portfolio
4. If adding a new position would breach cluster limit, skip or reduce size

**Pseudocode from spec:**
```python
def check_correlation_clustering(portfolio, new_stock, date):
    returns = get_returns_matrix(portfolio.symbols + [new_stock], date, lookback=60)
    corr_matrix = returns.corr()
    
    for held_stock in portfolio.symbols:
        if corr_matrix[new_stock][held_stock] > 0.7:
            cluster_weight = sum(portfolio.weight[s] for s in cluster)
            if cluster_weight > 0.30:
                return 'REDUCE_SIZE'  # Cap at cluster limit
    
    return 'OK'
```

**Files to create/modify:**
- `src/services/portfolio_controls_service.py` [MODIFY] — Add `check_correlation()` method
- Needs: `MarketDataRepository` to fetch historical closes for return calculation

**Data needed:** 60+ days of daily close prices per stock (already in `market_data` table).

---

## 3. VIX-Based Exposure Scaling (Spec Section 2.5, Control 4)

**Spec Requirement:** Scale portfolio exposure based on India VIX level.

**Scaling Rules from spec:**
```
India VIX < 15   → Full exposure (100% of target positions)
VIX 15-20        → 90% exposure
VIX 20-25        → 75% exposure
VIX 25-35        → 50% exposure
VIX > 35         → 25% exposure (crisis mode)
```

**Implementation Approach:**
1. **India VIX data feed** — Fetch from NSE API or Kite API (`INDIA VIX` instrument)
2. Multiply position sizes by exposure factor based on current VIX
3. Reduce max positions proportionally

**Files to create/modify:**
- `src/adaptors/vix_adaptor.py` [NEW] — Fetch India VIX data
- `config/strategies_config.py` [MODIFY] — Add `VIXScalingConfig` with thresholds
- `src/services/portfolio_controls_service.py` [MODIFY] — Add `get_vix_exposure_factor()`
- `src/services/actions_service.py` [MODIFY] — Apply factor to position sizing

**Data needed:** Real-time or EOD India VIX value (not currently available in the system).

---

## 4. Sector-Normalized Ranking (Spec Section 1.4 — Optional Enhancement)

**Spec Requirement:** Rank stocks within their sector before cross-sectional ranking to avoid sector bias.

**Current state:** `InstrumentsModel` already has `sector` column populated.

**Implementation Approach:**
1. Group stocks by `InstrumentsModel.sector`
2. Calculate percentile rank within each sector group
3. Then combine sector-normalized ranks for cross-sectional comparison
4. Prevents scenarios where one hot sector dominates the top rankings

**Pseudocode:**
```python
def sector_normalized_rank(df, column, sector_column='sector'):
    # Rank within sector first
    df['sector_rank'] = df.groupby(sector_column)[column].transform(
        lambda x: x.rank(pct=True) * 100
    )
    # Then rank the sector ranks cross-sectionally
    df['final_rank'] = df['sector_rank'].rank(pct=True) * 100
    return df
```

**Files to modify:**
- `src/services/percentile_service.py` [MODIFY] — Add sector-aware ranking option
- `src/utils/ranking_utils.py` [MODIFY] — Add `sector_percentile_rank()` function
- Need to join `InstrumentsModel.sector` with indicator data in ranking pipeline

**Data needed:** Already available in `InstrumentsModel.sector`.

---

## 5. Stress Testing Module (Spec Section 3.5)

**Spec Requirement:** Sensitivity analysis to validate strategy robustness.

**Tests to implement:**

| Test | What it varies | Expected behavior |
|---|---|---|
| Cost sensitivity | 2× and 3× transaction costs | Returns degrade gracefully, not collapse |
| Universe sensitivity | Top 200, 300, 500 stocks | Core alpha persists across sizes |
| Rebalancing frequency | Weekly vs bi-weekly vs monthly | Monthly shouldn't outperform weekly significantly |
| Portfolio size | 8, 12, 15, 20 positions | Diminishing returns above 15 |
| Factor weight sensitivity | ±10% on each weight | Score stability under perturbation |

**Implementation Approach:**
1. Create `src/backtesting/stress_test.py` that runs multiple backtests with varied parameters
2. Collect metrics from each run (depends on `metrics.py` module from Phase 8)
3. Output comparison table

**Files to create:**
- `src/backtesting/stress_test.py` [NEW] — Orchestrates parameter sweeps
- `src/api/v1/routes/backtest_routes.py` [MODIFY] — Add stress test endpoint

**Dependencies:** Requires `src/utils/metrics.py` (Phase 8 of current plan) and working backtester.

---

## 6. Survivorship Bias Prevention (Spec Section 3.1)

**Spec Requirement:** Use historical constituent files so backtests don't include stocks that were later added to the index.

**Implementation Approach:**
1. Obtain historical Nifty 500 constituent lists (monthly or quarterly snapshots from NSE)
2. Store in a new `index_constituents` table with `(date, symbol)` composite key
3. During backtesting, filter universe to only include stocks that were in the index on each rebalance date
4. Handle delistings: if a stock is delisted, force-sell at last available price minus slippage

**Files to create/modify:**
- `src/models/index_constituents_model.py` [NEW]
- `src/repositories/index_constituents_repository.py` [NEW]
- `src/backtesting/runner.py` [MODIFY] — Filter universe per historical date
- Data ingestion script for NSE constituent files

**Data needed:** Historical Nifty 500 constituent CSVs from NSE (not currently available).

---

## 7. Automated Test Suite (Gap Analysis Issue #11)

**Current state:** Zero test files in the entire codebase.

**Recommended test structure:**
```
tests/
├── unit/
│   ├── test_ranking_utils.py
│   ├── test_transaction_costs_utils.py
│   ├── test_tax_utils.py
│   ├── test_sizing_utils.py
│   ├── test_stoploss_utils.py
│   ├── test_factors_service.py
│   └── test_metrics.py
├── integration/
│   ├── test_indicators_service.py
│   ├── test_percentile_service.py
│   ├── test_score_service.py
│   └── test_actions_service.py
└── e2e/
    ├── test_backtest_runner.py
    └── test_api_endpoints.py
```

**Priority order:**
1. Utils (pure functions, easy to test) — `ranking_utils`, `transaction_costs_utils`, `tax_utils`
2. Services (need mock repos) — `factors_service`, `score_service`
3. Integration — `backtesting/runner.py`

**Tools:** `pytest` + `pytest-cov` for coverage.

---

## 8. YFinance Adaptor Enhancement (Gap Analysis Issue #15)

**Current state:** Only has `get_stock_info()` for initial instrument setup.

**Potential enhancements:**
- Historical data fetching as fallback when Kite API is unavailable
- Fundamental data (P/E, D/E, market cap updates) for future fundamental filters
- Dividend data for total return calculations

**Low priority** — Kite API is the primary data source.

---

## 9. Production WSGI Setup (Gap Analysis Issue #18)

**Current state:** App runs via `python run.py` with `app.run(debug=True)`.

**For production:**
- Add Gunicorn/Waitress configuration
- Create `wsgi.py` entry point
- Add `Procfile` or systemd service file
- Set up proper logging (file rotation, separate error log)
- Environment-based config (dev/staging/prod)

---

## Implementation Order Recommendation

When implementing deferred items, the recommended order is:

1. **Automated Tests** (#7) — Foundation for safe refactoring
2. **Performance Metrics** already in plan — prerequisite for #5
3. **Sector-Normalized Ranking** (#4) — Data already available, low effort
4. **Stress Testing** (#5) — Validates strategy robustness
5. **Correlation Clustering** (#2) — Data available, moderate effort
6. **Adaptive Rebalancing** (#1) — Needs Nifty 50 data
7. **VIX-Based Scaling** (#3) — Needs VIX data feed
8. **Survivorship Bias** (#6) — Needs historical constituent data
9. **Production WSGI** (#9) — When ready to deploy
10. **YFinance Enhancement** (#8) — Only if needed
