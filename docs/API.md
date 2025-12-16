# API Reference

Base URL: `http://localhost:5000`

---

## Orchestration Endpoints

### GET /home
Fetch latest market data for all instruments.

### GET /day0
Initialize stock universe from NSE/BSE CSV files.

### GET /update_indicators
Calculate technical indicators for all stocks.

### GET /latest_rank
Generate composite scores and save rankings to database.

---

## Risk Configuration

### GET /risk_config
Get current portfolio risk settings.

**Response:**
```json
{
  "id": 1,
  "initial_capital": 100000.0,
  "current_capital": 100000.0,
  "risk_per_trade": 1000.0,
  "max_positions": 15,
  "buffer_percent": 0.25,
  "exit_threshold": 40.0,
  "stop_loss_multiplier": 2.0
}
```

### PUT /risk_config
Update risk configuration.

**Request:**
```json
{
  "initial_capital": 200000,
  "risk_per_trade": 2000,
  "max_positions": 20
}
```

---

## Portfolio Management

### GET /invested
List all current positions.

### POST /invested
Add a new position.

**Request:**
```json
{
  "tradingsymbol": "RELIANCE",
  "buy_price": 2500.0,
  "num_shares": 10
}
```

**Response:** Position with calculated stop-loss values.

### DELETE /invested/{symbol}
Remove a position.

---

## Rankings

### GET /ranking/top20
Get top 20 ranked stocks with investment status.

**Response:**
```json
[
  {
    "tradingsymbol": "SMCGLOBAL",
    "composite_score": 97.54,
    "rank_position": 1,
    "is_invested": false,
    "ranking_date": "2025-12-16"
  }
]
```

---

## Actions

### GET /actions
Get all pending (unexecuted) actions.

### POST /actions/generate
Generate trade recommendations based on rankings.

**Request:**
```json
{
  "ranking_date": "2025-12-16"  // Optional, defaults to today
}
```

**Response:**
```json
[
  {
    "action_type": "BUY",
    "tradingsymbol": "HINDZINC",
    "units": 31,
    "expected_price": 566.5,
    "amount": 17561.5,
    "buy_price_min": 549.51,
    "buy_price_max": 577.83,
    "composite_score": 93.7,
    "status": "PENDING",
    "reason": "Filling vacancy - Score 93.7"
  }
]
```

### POST /actions/{id}/execute
Mark action as executed, update capital and positions.

---

## Instruments

### GET /instruments
List all instruments.

### POST /instruments
Bulk insert instruments.

---

## Market Data

### GET /market_data/latest/{symbol}
Get latest OHLCV for a symbol.

### GET /indicators/latest/{symbol}
Get latest technical indicators for a symbol.

---

## Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 404 | Not Found |
| 500 | Server Error |
