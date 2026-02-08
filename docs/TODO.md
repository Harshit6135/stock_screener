# Future Work & Enhancements

> Items from the implementation spec that are planned for future development.

---

## High Priority

### 1. Backtesting Integration
- [ ] Integrate new services (`factors_service`, `portfolio_controls_service`) into `backtesting_new.py`
- [ ] Add walk-forward testing framework
- [ ] Implement survivorship-bias-free historical universe

### 2. Configuration API Endpoints
- [ ] Create REST endpoints for runtime config management
- [ ] Allow updating factor weights, thresholds via API
- [ ] Persist config changes to database

### 3. Database Migrations
- [ ] Run `flask db migrate` for new indicator columns (`roc_60`, `roc_125`, `atr_spike`)
- [ ] Apply schema changes with `flask db upgrade`

---

## Medium Priority

### 4. Sector-Normalized Ranking
- [ ] Implement percentile ranking within sector groups
- [ ] Prevents sector bias in composite scores
- [ ] Config option to toggle sector vs universe ranking

### 5. Adaptive Rebalancing Frequency
```python
# Logic from spec:
if trend_efficiency > 0.50 and positive_days > 0.60:
    return 'MONTHLY'  # Strong uptrend - let winners run
elif trend_efficiency > 0.50 and positive_days < 0.40:
    return 'WEEKLY'   # Strong downtrend - cut losers fast
else:
    return 'BIWEEKLY' # Default
```

### 6. Correlation Clustering Detection
- [ ] Track 60-day returns correlation between holdings
- [ ] Alert when >3 holdings have correlation >0.70
- [ ] Reduce exposure to highly correlated positions

### 7. Market Cap Adjustment for Position Sizing
- [ ] Small cap (<₹5K Cr): 50% size reduction
- [ ] Mid cap (<₹10K Cr): 75% size reduction
- [ ] Prevents over-allocation to illiquid names

---

## Low Priority (Future Enhancements)

### 8. Real-Time Data Integration
- [ ] Replace EOD data with real-time/intraday feeds
- [ ] Automated universe updates
- [ ] Live corporate action handling (splits, bonuses)

### 9. Order Execution Interface
- [ ] Generate order CSV for broker upload
- [ ] API integration with Kite/Zerodha
- [ ] Track execution prices vs expected prices

### 10. Performance Monitoring Dashboard
- [ ] Equity curve visualization
- [ ] Factor performance attribution
- [ ] Risk metrics (Sharpe, Calmar, Max DD)
- [ ] Trade log analysis

### 11. Stress Testing Module
- [ ] Transaction cost sensitivity (0.5x to 2.0x)
- [ ] Universe size sensitivity (₹5Cr to ₹20Cr turnover)
- [ ] Rebalancing frequency impact (weekly/biweekly/monthly)
- [ ] Portfolio size impact (5 to 20 holdings)

---

## Backtest Integrity Checklist

### Survivorship Bias Prevention
- [ ] Use historical index constituents (not current)
- [ ] Include delisted stocks with `delisting_date`
- [ ] Download from NSE historical data portal

### Look-Ahead Bias Prevention
- [ ] Entry on T+1 open (signal on T close)
- [ ] Percentile ranks use only data available at T
- [ ] No future data in indicator calculations

### Realistic Execution
- [ ] Entry/exit at next-day open + 0.1% slippage
- [ ] Apply full transaction cost model
- [ ] Skip trades if order > 15% daily volume

---

## Performance Sanity Checks

| Metric | Suspicious If |
|--------|---------------|
| Sharpe > 3.0 | Check for data leakage |
| Max DD < 10% | Unrealistic for momentum |
| Win Rate > 70% | Verify trade logic |
| Profit Factor > 3.0 | Double-check |

---

## Expected Performance (After Full Implementation)

| Metric | Baseline | Target |
|--------|----------|--------|
| CAGR | 18-22% | 22-28% |
| Sharpe | 1.2-1.5 | 1.6-2.0 |
| Max DD | 25-30% | 18-24% |
| Win Rate | 55-60% | 58-64% |

---

*Last updated: 2026-02-08*
