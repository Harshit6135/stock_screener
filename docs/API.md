# API Reference

Base URL: `http://localhost:5000`

**Swagger UI**: [http://localhost:5000/swagger-ui](http://localhost:5000/swagger-ui)

---

## Dashboard & Orchestration Endpoints

> [!NOTE]
> These endpoints are internal orchestration routes that trigger batch operations. They don't accept request bodies.

### GET /

Render the main dashboard UI.

---

### GET /day0

Initialize stock universe from NSE/BSE CSV files. Runs the Day 0 setup process.

**Response:** `"Day 0 completed."`

---

### GET /update_market_data

Fetch latest market data for all instruments from Kite API.

**Response:** `"Market data update completed."`

---

### GET /update_indicators

Calculate technical indicators for all stocks based on market data.

**Response:** `"Calculation of Indicators completed."`

---

### GET /latest_rank

Generate composite scores, rank stocks, and save rankings to database.

**Response:** `"Ranking completed and saved."`

---

### GET /api/actions

Get actions with optional date filter, sorted by composite_score descending.

**Query Parameters:**

| Parameter | Type   | Required | Description                          |
|-----------|--------|----------|--------------------------------------|
| `date`    | string | No       | Filter by action date (YYYY-MM-DD)   |

**Response:**
```json
[
  {
    "action_date": "2025-12-16",
    "action_type": "BUY",
    "tradingsymbol": "HINDZINC",
    "composite_score": 93.7,
    "units": 31,
    "expected_price": 566.5,
    "amount": 17561.5,
    "swap_from_symbol": null,
    "swap_from_units": null,
    "swap_from_price": null,
    "status": "PENDING"
  }
]
```

---

## Instruments

### GET /instruments

Get all instruments.

**Response:**
```json
[
  {
    "instrument_token": 738561,
    "exchange_token": "2884",
    "tradingsymbol": "RELIANCE",
    "name": "Reliance Industries",
    "exchange": "NSE"
  }
]
```

---

### POST /instruments

Bulk insert instruments.

**Request Body:** Array of instruments
```json
[
  {
    "instrument_token": 738561,
    "exchange_token": "2884",
    "tradingsymbol": "RELIANCE",
    "name": "Reliance Industries",
    "exchange": "NSE"
  }
]
```

| Field             | Type    | Required | Description                    |
|-------------------|---------|----------|--------------------------------|
| `instrument_token`| integer | **Yes**  | Unique Kite instrument token   |
| `exchange_token`  | string  | No       | Exchange token                 |
| `tradingsymbol`   | string  | No       | Trading symbol                 |
| `name`            | string  | No       | Company name                   |
| `exchange`        | string  | No       | Exchange (NSE/BSE)             |

**Response:** `201 Created` with inserted data

---

### DELETE /instruments

Delete all instruments.

**Response:**
```json
{
  "message": "Deleted 1500 instruments."
}
```

---

### GET /instruments/{instrument_token}

Get a specific instrument by token.

**Path Parameters:**

| Parameter         | Type    | Required | Description          |
|-------------------|---------|----------|----------------------|
| `instrument_token`| integer | **Yes**  | Instrument token ID  |

**Response:**
```json
{
  "instrument_token": 738561,
  "exchange_token": "2884",
  "tradingsymbol": "RELIANCE",
  "name": "Reliance Industries",
  "exchange": "NSE"
}
```

---

### PUT /instruments/{instrument_token}

Update a specific instrument.

**Path Parameters:**

| Parameter         | Type    | Required | Description          |
|-------------------|---------|----------|----------------------|
| `instrument_token`| integer | **Yes**  | Instrument token ID  |

**Request Body:**
```json
{
  "tradingsymbol": "RELIANCE",
  "name": "Reliance Industries Ltd",
  "exchange": "NSE"
}
```

---

## Market Data

### POST /market_data

Bulk insert market data entries (OHLCV).

**Request Body:** Array of market data records
```json
[
  {
    "instrument_token": 738561,
    "tradingsymbol": "RELIANCE",
    "exchange": "NSE",
    "date": "2025-12-16",
    "open": 2505.0,
    "high": 2520.0,
    "low": 2490.0,
    "close": 2515.0,
    "volume": 1500000
  }
]
```

| Field             | Type    | Required | Description                    |
|-------------------|---------|----------|--------------------------------|
| `instrument_token`| integer | **Yes**  | Instrument token               |
| `tradingsymbol`   | string  | **Yes**  | Trading symbol                 |
| `exchange`        | string  | **Yes**  | Exchange (NSE/BSE)             |
| `date`            | string  | **Yes**  | Date (YYYY-MM-DD)              |
| `open`            | float   | No       | Opening price                  |
| `high`            | float   | No       | High price                     |
| `low`             | float   | No       | Low price                      |
| `close`           | float   | No       | Closing price                  |
| `volume`          | float   | No       | Volume traded                  |

**Response:** `201 Created`

---

### GET /market_data/query

Query market data by instrument within a date range.

**Request Body (JSON):**
```json
{
  "tradingsymbol": "RELIANCE",
  "start_date": "2025-01-01",
  "end_date": "2025-12-16"
}
```

| Field             | Type    | Required | Description                                      |
|-------------------|---------|----------|--------------------------------------------------|
| `instrument_token`| integer | No*      | Instrument token                                 |
| `tradingsymbol`   | string  | No*      | Trading symbol                                   |
| `start_date`      | string  | **Yes**  | Start date (YYYY-MM-DD)                          |
| `end_date`        | string  | **Yes**  | End date (YYYY-MM-DD)                            |

> *Either `instrument_token` or `tradingsymbol` must be provided.

**Response:**
```json
[
  {
    "instrument_token": 738561,
    "tradingsymbol": "RELIANCE",
    "exchange": "NSE",
    "date": "2025-12-16",
    "open": 2505.0,
    "high": 2520.0,
    "low": 2490.0,
    "close": 2515.0,
    "volume": 1500000
  }
]
```

---

### GET /market_data/max_date

Get the maximum (latest) date for each instrument's market data.

**Response:**
```json
[
  {
    "instrument_token": 738561,
    "max_date": "2025-12-16"
  }
]
```

---

### GET /market_data/latest/{tradingsymbol}

Get latest OHLCV data for a specific symbol.

**Path Parameters:**

| Parameter       | Type   | Required | Description      |
|-----------------|--------|----------|------------------|
| `tradingsymbol` | string | **Yes**  | Trading symbol   |

**Response:**
```json
{
  "instrument_token": 738561,
  "tradingsymbol": "RELIANCE",
  "exchange": "NSE",
  "date": "2025-12-16",
  "open": 2505.0,
  "high": 2520.0,
  "low": 2490.0,
  "close": 2515.0,
  "volume": 1500000
}
```

---

## Indicators

### POST /indicators

Bulk insert indicator entries.

**Request Body:** Array of indicator records
```json
[
  {
    "instrument_token": 738561,
    "tradingsymbol": "RELIANCE",
    "exchange": "NSE",
    "date": "2025-12-16",
    "ema_50": 2480.5,
    "ema_200": 2350.2,
    "rsi_14": 62.5,
    "roc_10": 3.2,
    "roc_20": 5.1,
    "sma_20": 2490.0,
    "atrr_14": 45.5,
    "macd_12_26_9": 15.2,
    "macdh_12_26_9": 3.5,
    "macds_12_26_9": 11.7,
    "ppo_12_26_9": 0.65,
    "ppoh_12_26_9": 0.12,
    "ppos_12_26_9": 0.53,
    "stochk_14_3_3": 75.2,
    "stochd_14_3_3": 72.8,
    "bbl_20_2_2": 2420.0,
    "bbm_20_2_2": 2490.0,
    "bbu_20_2_2": 2560.0,
    "bbb_20_2_2": 5.6,
    "bbp_20_2_2": 0.68,
    "rsi_signal_ema_3": 61.2,
    "volume_sma_20": 1200000,
    "price_vol_correlation": 0.45,
    "percent_b": 0.68,
    "ema_50_slope": 0.15,
    "distance_from_ema_200": 7.0,
    "risk_adjusted_return": 1.25,
    "rvol": 1.3
  }
]
```

| Field                   | Type    | Required | Description                        |
|-------------------------|---------|----------|------------------------------------|
| `instrument_token`      | integer | **Yes**  | Instrument token                   |
| `tradingsymbol`         | string  | **Yes**  | Trading symbol                     |
| `exchange`              | string  | **Yes**  | Exchange (NSE/BSE)                 |
| `date`                  | string  | **Yes**  | Date (YYYY-MM-DD)                  |
| `ema_50`                | float   | No       | 50-period EMA                      |
| `ema_200`               | float   | No       | 200-period EMA                     |
| `rsi_14`                | float   | No       | 14-period RSI                      |
| `roc_10`                | float   | No       | 10-period Rate of Change           |
| `roc_20`                | float   | No       | 20-period Rate of Change           |
| `sma_20`                | float   | No       | 20-period SMA                      |
| `atrr_14`               | float   | No       | 14-period ATR (as ratio)           |
| `macd_12_26_9`          | float   | No       | MACD line                          |
| `macdh_12_26_9`         | float   | No       | MACD histogram                     |
| `macds_12_26_9`         | float   | No       | MACD signal                        |
| `ppo_12_26_9`           | float   | No       | PPO line                           |
| `ppoh_12_26_9`          | float   | No       | PPO histogram                      |
| `ppos_12_26_9`          | float   | No       | PPO signal                         |
| `stochk_14_3_3`         | float   | No       | Stochastic %K                      |
| `stochd_14_3_3`         | float   | No       | Stochastic %D                      |
| `stochh_14_3_3`         | float   | No       | Stochastic histogram               |
| `bbl_20_2_2`            | float   | No       | Bollinger Band lower               |
| `bbm_20_2_2`            | float   | No       | Bollinger Band middle              |
| `bbu_20_2_2`            | float   | No       | Bollinger Band upper               |
| `bbb_20_2_2`            | float   | No       | Bollinger Bandwidth                |
| `bbp_20_2_2`            | float   | No       | Bollinger %B                       |
| `rsi_signal_ema_3`      | float   | No       | RSI signal (3-period EMA)          |
| `volume_sma_20`         | float   | No       | 20-period volume SMA               |
| `price_vol_correlation` | float   | No       | Price-volume correlation           |
| `percent_b`             | float   | No       | Percent B indicator                |
| `ema_50_slope`          | float   | No       | 50-EMA slope                       |
| `distance_from_ema_200` | float   | No       | Distance from 200-EMA (%)          |
| `risk_adjusted_return`  | float   | No       | Risk-adjusted return               |
| `rvol`                  | float   | No       | Relative volume                    |

**Response:** `201 Created`

---

### GET /indicators/latest/{tradingsymbol}

Get latest technical indicators for a symbol.

**Path Parameters:**

| Parameter       | Type   | Required | Description      |
|-----------------|--------|----------|------------------|
| `tradingsymbol` | string | **Yes**  | Trading symbol   |

**Response:** Single indicator record (same structure as POST body item)

---

## Risk Configuration

### GET /risk_config

Get current portfolio risk settings. Creates default config if none exists.

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
  "stop_loss_multiplier": 2.0,
  "created_at": "2025-12-16T00:00:00",
  "updated_at": "2025-12-16T00:00:00"
}
```

---

### PUT /risk_config

Update risk configuration.

**Request Body:**
```json
{
  "initial_capital": 200000,
  "current_capital": 180000,
  "risk_per_trade": 2000,
  "max_positions": 20,
  "buffer_percent": 0.20,
  "exit_threshold": 35.0,
  "stop_loss_multiplier": 2.5
}
```

| Field                | Type   | Required | Default   | Description                              |
|----------------------|--------|----------|-----------|------------------------------------------|
| `initial_capital`    | float  | No       | 100000.0  | Starting capital                         |
| `current_capital`    | float  | No       | 100000.0  | Available capital                        |
| `risk_per_trade`     | float  | No       | 1000.0    | Maximum risk per trade (₹)               |
| `max_positions`      | int    | No       | 15        | Maximum simultaneous positions           |
| `buffer_percent`     | float  | No       | 0.25      | Buffer percentage for price slippage     |
| `exit_threshold`     | float  | No       | 40.0      | Exit threshold score                     |
| `stop_loss_multiplier`| float | No       | 2.0       | ATR multiplier for stop-loss             |

**Response:** Updated config object

---

## Portfolio Management (Invested Stocks)

### GET /invested

List all current positions.

**Response:**
```json
[
  {
    "id": 1,
    "tradingsymbol": "RELIANCE",
    "instrument_token": 738561,
    "exchange": "NSE",
    "buy_price": 2500.0,
    "num_shares": 10,
    "buy_date": "2025-12-10",
    "atr_at_entry": 45.5,
    "initial_stop_loss": 2409.0,
    "current_stop_loss": 2409.0,
    "current_score": 85.5,
    "last_updated": "2025-12-16T10:00:00",
    "investment_value": 25000.0
  }
]
```

---

### POST /invested

Add a new invested position. Stop-loss is auto-calculated from ATR.

**Request Body:**
```json
{
  "tradingsymbol": "RELIANCE",
  "buy_price": 2500.0,
  "num_shares": 10
}
```

| Field           | Type   | Required | Description          |
|-----------------|--------|----------|----------------------|
| `tradingsymbol` | string | **Yes**  | Trading symbol       |
| `buy_price`     | float  | **Yes**  | Entry price          |
| `num_shares`    | int    | **Yes**  | Number of shares     |

**Response:** `201 Created` with position including calculated stop-loss

---

### DELETE /invested

Clear all invested positions.

**Response:**
```json
{
  "message": "Deleted 10 positions"
}
```

---

### GET /invested/{tradingsymbol}

Get a specific invested position.

**Path Parameters:**

| Parameter       | Type   | Required | Description      |
|-----------------|--------|----------|------------------|
| `tradingsymbol` | string | **Yes**  | Trading symbol   |

**Response:** Single invested position object

---

### DELETE /invested/{tradingsymbol}

Remove a specific position from portfolio.

**Path Parameters:**

| Parameter       | Type   | Required | Description      |
|-----------------|--------|----------|------------------|
| `tradingsymbol` | string | **Yes**  | Trading symbol   |

**Response:**
```json
{
  "message": "Removed RELIANCE from portfolio"
}
```

---

## Score Calculation

### POST /api/v1/score/generate

Generate composite scores incrementally from the last calculated date.

**Response:**
```json
{
  "message": "Generated composite scores for 5 dates (2025-12-11 to 2025-12-16)"
}
```

---

### POST /api/v1/score/recalculate

Recalculate ALL composite scores from scratch. Use when strategy weights have been updated.

**Response:**
```json
{
  "message": "Recalculated 5000 composite scores across 50 dates"
}
```

---

### POST /api/v1/score/generate_avg

Generate weekly average scores incrementally. For each Friday, calculates the average of that week's (Mon-Fri) daily composite scores.

**Response:**
```json
{
  "message": "Generated avg_scores for 3 Fridays"
}
```

---

### POST /api/v1/score/recalculate_avg

Recalculate ALL weekly average scores from scratch.

**Response:**
```json
{
  "message": "Recalculated avg_scores for 10 Fridays"
}
```

---

### GET /api/v1/score/top/{n}

Get top N stocks by weekly average composite score. Date is normalized to the nearest Friday.

**Path Parameters:**

| Parameter | Type    | Required | Description                |
|-----------|---------|----------|----------------------------|
| `n`       | integer | **Yes**  | Number of top stocks       |

**Query Parameters:**

| Parameter | Type   | Required | Description                          |
|-----------|--------|----------|--------------------------------------|
| `date`    | string | No       | Date to query (YYYY-MM-DD), normalized to Friday |

**Response:**
```json
[
  {
    "tradingsymbol": "SMCGLOBAL",
    "composite_score": 97.54,
    "rank": 1,
    "is_invested": false,
    "ranking_date": "2025-12-13",
    "close_price": 245.50
  }
]
```

---

### GET /api/v1/score/symbol/{symbol}

Get weekly average score for a specific symbol. Date is normalized to the nearest Friday.

**Path Parameters:**

| Parameter | Type   | Required | Description      |
|-----------|--------|----------|------------------|
| `symbol`  | string | **Yes**  | Trading symbol   |

**Query Parameters:**

| Parameter | Type   | Required | Description                          |
|-----------|--------|----------|--------------------------------------|
| `date`    | string | No       | Date to query (YYYY-MM-DD), normalized to Friday |

**Response:**
```json
{
  "tradingsymbol": "RELIANCE",
  "composite_score": 85.5,
  "rank": 0,
  "is_invested": false,
  "ranking_date": "2025-12-13",
  "close_price": 2515.0
}
```

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
    "rank": 1,
    "is_invested": false,
    "ranking_date": "2025-12-16"
  }
]
```

---

### POST /ranking

Bulk insert ranking data.

**Request Body:** Array of ranking records
```json
[
  {
    "tradingsymbol": "SMCGLOBAL",
    "ranking_date": "2025-12-16",
    "composite_score": 97.54,
    "rank": 1,
    "trend_rank": 95.0,
    "final_trend_score": 92.5,
    "final_momentum_score": 88.0,
    "vol_score": 85.5,
    "final_structure_score": 90.0
  }
]
```

**Response:**
```json
{
  "message": "Inserted 100 ranking records"
}
```

---

## Actions (Trade Recommendations)

### GET /actions

Get all pending (unexecuted) actions.

**Response:**
```json
[
  {
    "id": 1,
    "action_date": "2025-12-16",
    "action_type": "BUY",
    "tradingsymbol": "HINDZINC",
    "units": 31,
    "expected_price": 566.5,
    "amount": 17561.5,
    "composite_score": 93.7,
    "buy_price_min": 549.51,
    "buy_price_max": 577.83,
    "swap_from_symbol": null,
    "swap_from_units": null,
    "swap_from_price": null,
    "status": "PENDING",
    "reason": "Filling vacancy - Score 93.7",
    "executed": false,
    "executed_at": null,
    "created_at": "2025-12-16T08:00:00"
  }
]
```

---

### POST /actions/generate

Generate trade recommendations based on current rankings and portfolio.

**Request Body:**
```json
{
  "ranking_date": "2025-12-16"
}
```

| Field          | Type   | Required | Default | Description                     |
|----------------|--------|----------|---------|---------------------------------|
| `ranking_date` | string | No       | Today   | Date to use for rankings (YYYY-MM-DD) |

**Response:** `201 Created` with array of generated actions

```json
[
  {
    "id": 1,
    "action_date": "2025-12-16",
    "action_type": "BUY",
    "tradingsymbol": "HINDZINC",
    "units": 31,
    "expected_price": 566.5,
    "amount": 17561.5,
    "composite_score": 93.7,
    "buy_price_min": 549.51,
    "buy_price_max": 577.83,
    "status": "PENDING",
    "reason": "Filling vacancy - Score 93.7"
  },
  {
    "action_type": "SWAP",
    "tradingsymbol": "NEWSTOCK",
    "units": 25,
    "expected_price": 400.0,
    "amount": 10000.0,
    "composite_score": 95.0,
    "swap_from_symbol": "OLDSTOCK",
    "swap_from_units": 20,
    "swap_from_price": 500.0,
    "status": "PENDING",
    "reason": "Swap: OLDSTOCK (score 45.0) → NEWSTOCK (score 95.0)"
  }
]
```

> [!IMPORTANT]
> Action types include: `BUY`, `SELL`, `SWAP`. For `SWAP` actions, the `swap_from_*` fields contain details of the stock being sold.

---

### POST /actions/{action_id}/execute

Mark an action as executed and update capital/positions accordingly.

**Path Parameters:**

| Parameter   | Type    | Required | Description   |
|-------------|---------|----------|---------------|
| `action_id` | integer | **Yes**  | Action ID     |

**Response:** Updated action with `executed: true` and `status: "INVESTED"`

---

## Status Codes

| Code | Meaning                                |
|------|----------------------------------------|
| 200  | Success                                |
| 201  | Created                                |
| 400  | Bad Request (validation error)         |
| 404  | Not Found                              |
| 500  | Server Error (database/internal error) |

---

## Error Response Format

All errors return JSON in this format:
```json
{
  "message": "Error description here"
}
```
