# Pending Items

> **Last Updated:** 2026-02-22

The following features and tasks are specified in the original implementation specifications but have not yet been implemented in the codebase.

## High Priority

- **Real-Time Data Integration**: Replace EOD data with real-time/intraday feeds via Kite WebSocket. Implement live ticker for dashboard and streaming alerts for Stop-Loss hits.
- **Order Execution Module**:  Integrate Kite Connect "Place Order" API for generated actions. Add basket order support for multiple trades (TWAP/VWAP).
- **Sector-Normalized Ranking**: Rank stocks within their specific sectors rather than comparing a bank directly to an IT services firm for more robust factor scoring.

## Medium Priority

- **Cost-Aware Swaps**: Swap buffer should be dynamic and consider the precise transaction and expected tax costs before generating a SWAP action.
- **Tax-Aware Holding Logic**: Incorporate the `should_hold_for_ltcg` recommendation directly into standard swap logic to bias toward holding if it's nearing the 365-day LTCG threshold.
- **Adaptive Rebalancing Frequency**: Change rebalancing from strictly weekly to bi-weekly or monthly based on the current market regime (e.g. increase frequency in high volatility).
- **Correlation Clustering**: Map portfolios on a heatmap to avoid adding highly correlated stocks. Auto-suggest decorrelated candidates.
- **Market Cap Constraints**: Apply scaling factors in position sizing based on market cap (e.g., 50% for small caps, 75% for mid caps).
- **Portfolio-Level Risk Controls**: Implement drawdown pauses (circuit breakers), sector concentration limits across the portfolio, and macro index filters (e.g., VIX).
- **Fundamental Filters**: Enforce light fundamental filters in Day 0 or screener (e.g., Debt/Equity < 2.0, trailing EPS > 0).

## Low Priority / Backtesting 

- **Survivorship-Bias-Free Universe**: Use historical index constituents instead of static CSV lists for backtesting.
- **Walk-Forward Backtesting**: Support multiple windows rolling across time instead of single-pass, to prevent over-fitting.
- **Delisting & Corporate Actions Handling**: Adjust historical data gracefully for splits, bonuses, dividends, and removed listings.
- **Impact Cost in Position Sizing**: Integrate the impact models into theoretical position size maximums to ensure realistic portfolio slippage.
- **Stress Testing Engine**: Test against higher transaction costs, variations of the universe, and different portfolio scaling.
- **Performance Validation / Sanity Checks**: Automatically flag unrealistic backtests (e.g. Sharpe ratio > 3, excessive concentration).
- **Performance Attribution**: Report module allowing drill-down into P&L by factor, sector, or market cap.
- **Multi-User Support**: Add RBAC and support multiple concurrent accounts/family accounts.
- **AI/ML Enhancements**: RL to optimize feature weights over time or detect anomalies in price discovery.
