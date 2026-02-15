# Fix Summary Table Calculations

- [x] Fix `portfolio_value` to include remaining cash (holdings + cash)
- [x] Fix `portfolio_risk` to use holdings_value - stop_value
- [x] Fix `gain` to use `initial_capital` as baseline
- [x] Fix `gain_percentage` to divide by `initial_capital`
- [x] Verified `capital_risk` formula is correct (no change needed)
- [x] Syntax check passed
- [ ] Re-run backtest and verify summary table values
