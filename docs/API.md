# API Reference

> **Last Updated:** 2026-02-16

Complete reference for the Stock Screener V2 REST API.

**Base URL**: `http://localhost:5000`  
**Swagger UI**: [http://localhost:5000/api/v1/swagger](http://localhost:5000/api/v1/swagger)

---

## 🚀 App Orchestration

System-wide operations for data pipelines and maintenance.

### `POST /api/v1/app/run-pipeline`
Run the full data processing pipeline interactively.

**Body (JSON):**
```json
{
  "init": true,         // Step 1: Init instruments
  "marketdata": true,   // Step 2: Update prices
  "indicators": true,   // Step 3: Tech indicators
  "percentile": true,   // Step 4: Percentile ranks
  "score": true,        // Step 5: Composite scores
  "ranking": true       // Step 6: Weekly rankings
}
```

### `DELETE /api/v1/app/cleanup`
Delete data after a specific date (for resets).

**Query Params:**
- `start_date`: YYYY-MM-DD
- `marketdata`, `indicators`, `percentile`, `score`, `ranking`: bool (default true)

### `POST /api/v1/app/recalculate`
Force recalculation of downstream data (Percentile → Score → Ranking) from a specific date.

**Query Params:**
- `start_date`: YYYY-MM-DD

---

## 🛠️ Initialization

### `POST /api/v1/init/`
Run the Day 0 initialization process (Reads CSVs from `data/` → Filters → DB).

**Response:**
```json
{ "message": "Initialized 1543 instruments from NSE/BSE", "count": 1543 }
```

---

## ⚙️ Configuration

### `GET /api/v1/config/{config_name}`
Get current strategy configuration parameters.

### `PUT /api/v1/config/{config_name}`
Update strategy configuration at runtime.

**Body (JSON):**
```json
{
  "trend_strength_weight": 0.35,
  "exit_threshold": 45
}
```

---

## 📈 Data API

### Instruments
- `GET /api/v1/instruments`: List all instruments
- `GET /api/v1/instruments/{token}`: Get details for a token

### Market Data
- `GET /api/v1/market_data/latest/{symbol}`: Get latest OHLCV
- `POST /api/v1/market_data/`: Bulk insert OHLCV
- `GET /api/v1/market_data/query`: Query range (Body: symbol, start_date, end_date)

### Indicators
- `GET /api/v1/indicators/latest/{symbol}`: Get latest technical indicators
- `POST /api/v1/indicators/generate`: Run calculation for date

### Percentiles
- `POST /api/v1/percentile/update/{date}`: Generate percentiles for date
- `GET /api/v1/percentile/query/{date}`: Get all percentiles for date

### Scores
- `POST /api/v1/score/generate`: Generate composite scores
- `GET /api/v1/score/{symbol}?date=YYYY-MM-DD`: Get specific score

### Rankings
- `POST /api/v1/ranking/generate`: Generate weekly rankings
- `GET /api/v1/ranking/top/{n}?date={date}`: Get top N stocks
- `GET /api/v1/ranking/symbol/{symbol}?date={date}`: Get ranking for stock

---

## ⚡ Trading Actions

### `POST /api/v1/actions/generate`
Generate SELL/SWAP/BUY recommendations based on latest rankings.

**Query Params:**
- `date`: Date to generate actions for (defaults to today)

### `GET /api/v1/actions/`
List all pending actions.

### `POST /api/v1/actions/approve`
Approve all pending actions for execution. Sets execution price to next-day open.

### `POST /api/v1/actions/process`
Process approved actions → Updates Portfolio Holdings.

---

## 💼 Investments (Portfolio)

### `GET /api/v1/investment/holdings`
Get current portfolio holdings.

**Response:**
```json
[
  {
    "tradingsymbol": "RELIANCE",
    "buy_price": 2500,
    "num_shares": 10,
    "current_stop_loss": 2400,
    "buy_date": "2024-01-01"
  }
]
```

### `GET /api/v1/investment/summary`
Get portfolio summary (Total Value, Cash, XIRR).

### `POST /api/v1/investment/manual/buy`
Manually add a buy trade (bypassing strategy).

**Body:**
```json
{
  "symbol": "TCS",
  "date": "2024-02-16",
  "units": 5,
  "price": 3500
}
```

### `POST /api/v1/investment/manual/sell`
Manually add a sell trade.

### `POST /api/v1/investment/sync-prices`
Update current value of holdings with latest market prices.

### `GET /api/v1/investment/trade-journal`
Get complete trade history with P&L.

---

## 💰 Analysis Tools

### Transaction Costs
- `GET /api/v1/costs/roundtrip?trade_value=100000`: Estimate buy+sell costs
- `GET /api/v1/costs/position-size?atr=50&current_price=1000&portfolio_value=1000000`: Calculate size

### Tax Analysis
- `GET /api/v1/tax/estimate`: Estimate STCG/LTCG for a trade
- `GET /api/v1/tax/hold-for-ltcg`: Check if holding for LTCG is beneficial

---

## 🧪 Backtesting

### `POST /api/v1/backtest/run`
Run a historical simulation.

**Body (JSON):**
```json
{
  "start_date": "2023-01-01",
  "end_date": "2023-12-31",
  "config_name": "momentum_config",
  "check_daily_sl": true
}
```

**Response:**
JSON object containing:
- `summary`: Final value, CAGR, Max Drawdown
- `trades`: List of all executed trades
- `equity_curve`: Daily portfolio value series
- `report_text`: Detailed text report
- `report_path`: Path to saved CSV report
