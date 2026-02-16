# Future Work & Enhancements

> **Last Updated:** 2026-02-16

Roadmap for Stock Screener V2.

---

## 🔴 High Priority

### 1. Real-Time Data Integration
- [ ] Replace EOD data with real-time/intraday feeds via Kite WebSocket.
- [ ] Implement live ticker for dashboard.
- [ ] Streaming alerts for Stop-Loss hits.

### 2. Order Execution Module
- [ ] **One-Click Execution**: Integrate Kite Connect "Place Order" API for generated actions.
- [ ] **Order Batching**: Basket order support for 5+ trades.
- [ ] **Execution Algo**: Smart limit orders to minimize impact cost (TWAP/VWAP logic).

### 3. Sector-Normalized Ranking
- [ ] Implement ranking *within* sector groups (e.g., Auto, IT, Pharma).
- [ ] Prevents portfolio from ignoring defensive sectors during rotations.
- [ ] Config option to toggle `Sector vs Universe` ranking.

---

## 🟡 Medium Priority

### 4. Adaptive Rebalancing Frequency
- [ ] Dynamic switching between Weekly and Monthly rebalancing based on Regime.
- [ ] Logic:
  - Strong Uptrend (High Trend Efficiency) → **Monthly** (Let winners run)
  - Volatile/Downtrend → **Weekly** (Cut losses fast)

### 5. Correlation Clustering
- [ ] Detect clusters of highly correlated stocks in portfolio.
- [ ] Visual heatmap on dashboard.
- [ ] Automated suggestion to reduce exposure to a specific cluster.

### 6. Market Cap Constraints
- [ ] Variable position sizing based on Market Cap.
- [ ] Large Cap: 100% allocation allowed.
- [ ] Small/Micro Cap: Capped at 50% allocation (Liquidity safety).

---

## 🟢 Low Priority (Long Term)

### 7. Performance Attribution
- [ ] Breakdown returns by Factor (How much did Trend contribute vs Value vs Momentum?)
- [ ] Breakdown by Sector.

### 8. Multi-User Support
- [ ] Role-based access control (Admin vs Viewer).
- [ ] Multiple portfolio support (Family accounts).

### 9. AI/ML Enhancements
- [ ] Reinforcement learning for optimizing factor weights.
- [ ] Anomaly detection for data quality checks.

---

## ✅ Completed Items

- [x] **Core Architecture**: Routes → Services → Repo → Model layering.
- [x] **Data Pipeline**: KITE → Indicators → Scores → Rankings.
- [x] **Backtesting Engine**: Daily/Weekly simulation with separate DB.
- [x] **Configuration System**: Runtime strategy config via API.
- [x] **Transaction Costs**: Detailed Indian cost model.
- [x] **Tax Logic**: STCG/LTCG awareness.
- [x] **Documentation**: Comprehensive Setup, API, and Strategy docs.
