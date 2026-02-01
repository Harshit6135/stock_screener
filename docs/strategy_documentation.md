# Momentum Strategy Stock Screener - Technical Documentation

## Executive Summary

This is a **quantitative multi-factor momentum stock screener** designed for Indian equity markets. The system identifies high-momentum stocks using a sophisticated scoring framework, ranks them weekly, and provides trading signals for portfolio rebalancing with ATR-based risk management.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           DATA PIPELINE                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  1. InitService (Universe Selection)                                    │
│     ├── NSE.csv + BSE.csv → Merge → Filter (MCAP≥500cr, Price≥₹75)     │
│     └── yfinance → marketCap, sector, industry                          │
├─────────────────────────────────────────────────────────────────────────┤
│  2. MarketDataService (OHLCV Fetching)                                  │
│     ├── Kite API → Daily OHLCV                                          │
│     └── Corporate Action Detection (close mismatch → full refresh)      │
├─────────────────────────────────────────────────────────────────────────┤
│  3. IndicatorsService (Technical Analysis)                              │
│     └── pandas_ta → EMA, RSI, MACD, BBands, ATR, PPO, ROC, etc.        │
├─────────────────────────────────────────────────────────────────────────┤
│  4. PercentileService (Cross-Sectional Ranking)                         │
│     └── Daily percentile ranks across the universe                      │
├─────────────────────────────────────────────────────────────────────────┤
│  5. ScoreService (Composite Scoring)                                    │
│     └── Weighted factor combination → Daily composite score             │
├─────────────────────────────────────────────────────────────────────────┤
│  6. RankingService (Weekly Rankings)                                    │
│     └── Mon-Fri average → Friday-dated rankings (1 = highest)           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Factor Framework

### 1. Trend Strength (Weight: 30%)

| Sub-Factor | Indicator | Weight | Calculation |
|------------|-----------|--------|-------------|
| Trend Rank | `ema_50_slope` | 60% | Slope of 50-day EMA (percentile ranked) |
| Trend Extension Rank | `distance_from_ema_200` | 40% | Goldilocks curve scoring |

**Goldilocks Curve for Trend Extension:**
```
Distance from EMA200     Score
──────────────────────────────
< 0% (below EMA)         0
0-10%                    80    ← Starting new trend
10-40%                   100   ← Sweet spot (established trend)
40-50%                   70    ← Getting extended
> 50%                    40    ← Overextended (risky)
```

### 2. Momentum Velocity (Weight: 25%)

| Sub-Factor | Indicator | Weight | Calculation |
|------------|-----------|--------|-------------|
| RSI Rank | `rsi_signal_ema_3` | 60% | Non-linear RSI regime scoring |
| PPO Rank | `ppo_12_26_9` | 25% | Price Percentage Oscillator (percentile) |
| PPO Histogram Rank | `ppoh_12_26_9` | 15% | PPO histogram (percentile) |

**RSI Regime Scoring:**
```
RSI Value    Score    Interpretation
───────────────────────────────────────
< 40         0        Bearish/Oversold
40-50        25       Neutral-weak
50-70        100      ★ Sweet spot (healthy momentum)
70-85        90       Strong but caution
> 85         60       Overbought risk
```

### 3. Risk Efficiency (Weight: 20%)

| Sub-Factor | Indicator | Weight | Calculation |
|------------|-----------|--------|-------------|
| Efficiency Rank | `risk_adjusted_return` | 100% | Return / ATR ratio (percentile ranked) |

**Formula:** `risk_adjusted_return = ROC_10 / ATR%_14`

This rewards stocks giving higher returns per unit of volatility.

### 4. Volume Conviction (Weight: 15%)

| Sub-Factor | Indicator | Weight | Calculation |
|------------|-----------|--------|-------------|
| Relative Volume Rank | `rvol` | 70% | Volume / SMA(Volume, 20) |
| Price-Volume Correlation | `price_vol_correlation` | 30% | 20-day correlation |

**Interpretation:**
- High RVOL + positive correlation = institutional buying
- High RVOL + negative correlation = distribution warning

### 5. Structure (Weight: 10%)

| Sub-Factor | Indicator | Weight | Calculation |
|------------|-----------|--------|-------------|
| Structure Rank | `bbb_20_2_2` | 50% | Bollinger Band Width (percentile) |
| BB Position Rank | `percent_b` | 50% | %B position scoring |

**%B Scoring (Walking the Bands):**
```
%B Value     Score    Interpretation
───────────────────────────────────────
< 0.5        20       Weak/Middle of bands
0.5-0.8      60       Approaching upper band
0.8-1.1      100      ★ Walking the bands (strong momentum)
> 1.1        80       Breakout (sustainable if volume confirms)
```

---

## Composite Score Formula

```python
# Step 1: Calculate sub-factor scores
final_trend_score = trend_rank × 0.6 + trend_extension_rank × 0.4
final_momentum_score = momentum_rsi_rank × 0.6 + momentum_ppo_rank × 0.25 + momentum_ppoh_rank × 0.15
final_vol_score = rvolume_rank × 0.7 + price_vol_corr_rank × 0.3
final_structure_score = structure_rank × 0.5 + structure_bb_rank × 0.5

# Step 2: Calculate composite score
composite_score = (
    trend_strength_weight × final_trend_score +      # 0.30
    momentum_velocity_weight × final_momentum_score + # 0.25
    risk_efficiency_weight × efficiency_rank +        # 0.20
    conviction_weight × final_vol_score +             # 0.15
    structure_weight × final_structure_score          # 0.10
)
```

**Score Range:** 0-100 (higher = better momentum profile)

---

## Weekly Ranking System

1. **Daily composite scores** are calculated for each stock
2. **Weekly average** is computed from Monday to Friday
3. **Rank 1** = highest weekly average score
4. Rankings are dated on **Friday** of each week

---

## Trading Strategy Logic

### Parameters (Configurable)
| Parameter | Default | Description |
|-----------|---------|-------------|
| `initial_capital` | ₹100,000 | Starting portfolio value |
| `risk_threshold` | 1% | Max risk per trade (of capital) |
| `max_positions` | 10 | Maximum concurrent holdings |
| `buffer_percent` | 25% | Swap threshold (challenger must beat incumbent by this %) |
| `sl_multiplier` | 2 | ATR multiplier for stop-loss |

### Position Sizing (ATR-Based)

```python
risk_per_unit = ATR × sl_multiplier
max_risk = capital × (risk_threshold / 100)
units = floor(max_risk / risk_per_unit)
```

**Example:**
- Capital: ₹100,000
- Stock Price: ₹500
- ATR: ₹15
- Stop Distance: 15 × 2 = ₹30
- Risk per trade: ₹100,000 × 1% = ₹1,000
- Units: floor(1000 / 30) = 33 shares

### Weekly Rebalancing Logic

```
PHASE 1: SELL (Stop-Loss Check)
─────────────────────────────────
For each holding:
  • Fetch weekly low price
  • If low ≤ current_stop_loss → SELL (stop-loss hit)

PHASE 2: RETAIN
─────────────────────────────────
For holdings still in top_n:
  • Remove from top_n candidates (they stay)

PHASE 3: BUY (Fill Vacancies)
─────────────────────────────────
remaining_buys = max_positions - current_holdings
For i in range(remaining_buys):
  • BUY from remaining top_n candidates

PHASE 4: SWAP (Rotation)
─────────────────────────────────
For each remaining challenger in top_n:
  For each incumbent holding:
    If challenger_score > incumbent_score × (1 + buffer_percent):
      • SELL incumbent
      • BUY challenger
```

### Stop-Loss System (Hybrid)

Two trailing stop mechanisms run in parallel:

**1. ATR Trailing Stop:**
```python
new_stop = current_price - (ATR × sl_multiplier)
effective_stop = max(new_stop, previous_stop)  # Only moves up
```

**2. Hard Trailing Stop (10% increments):**
```python
gain_percent = (current_price - entry_price) / entry_price
tiers = int(gain_percent // 0.10)  # For every 10% gain
hard_stop = initial_stop × (1 + 0.10 × tiers)
```

**Combined:** `effective_stop = MAX(atr_stop, hard_stop)`

---

## Mathematical Verification

### 1. Percentile Ranking ✓
```python
percentile_rank = series.rank(pct=True) × 100
```
- Uses pandas `rank(pct=True)` which correctly handles ties
- Output: 0-100 scale

### 2. Score Weights ✓
```python
# Trend (0.30)
trend_rank_weight = 0.6
trend_extension_rank_weight = 0.4
# Sum = 1.0 ✓

# Momentum (0.25)
momentum_rsi_rank_weight = 0.6
momentum_ppo_rank_weight = 0.25
momentum_ppoh_rank_weight = 0.15
# Sum = 1.0 ✓

# Volume (0.15)
rvolume_rank_weight = 0.7
price_vol_corr_rank_weight = 0.3
# Sum = 1.0 ✓

# Structure (0.10)
structure_rank_weight = 0.5
structure_bb_rank_weight = 0.5
# Sum = 1.0 ✓

# Factor Weights
trend_strength_weight = 0.30
momentum_velocity_weight = 0.25
risk_efficiency_weight = 0.20
conviction_weight = 0.15
structure_weight = 0.10
# Sum = 1.0 ✓
```

### 3. Risk Calculation ✓
```python
capital_risk = units × (entry_price - stop_loss)
portfolio_risk = Σ(units × (current_price - current_sl))
```
- Correctly calculates downside exposure

### 4. Position Sizing ✓
```python
units = floor(risk_amount / stop_distance)
```
- Ensures no fractional shares
- Equalizes risk across positions (high-volatility stocks get fewer shares)

---

## Technical Indicators Used

| Indicator | Calculation | Purpose |
|-----------|-------------|---------|
| `EMA_50` | Exponential Moving Average (50-day) | Trend direction |
| `EMA_200` | Exponential Moving Average (200-day) | Long-term trend |
| `ema_50_slope` | Rate of change of EMA_50 | Trend strength |
| `distance_from_ema_200` | (Close - EMA200) / EMA200 | Extension measurement |
| `RSI_14` | Relative Strength Index (14-day) | Momentum |
| `rsi_signal_ema_3` | 3-day EMA of RSI | Smoothed RSI |
| `PPO_12_26_9` | (EMA12 - EMA26) / EMA26 × 100 | MACD normalized |
| `PPOH_12_26_9` | PPO - Signal | PPO histogram |
| `ATR_14` | Average True Range (14-day) | Volatility |
| `ATRR_14` | ATR / Close × 100 | Normalized ATR |
| `ROC_10` | (Close - Close[-10]) / Close[-10] × 100 | Rate of change |
| `RVOL` | Volume / SMA(Volume, 20) | Relative volume |
| `BBB_20_2_2` | (Upper - Lower) / Middle × 100 | Band width |
| `percent_b` | (Close - Lower) / (Upper - Lower) | Band position |
| `price_vol_correlation` | Correlation(Close, Volume, 20) | Volume quality |
| `risk_adjusted_return` | ROC_10 / ATRR_14 | Return per risk |

---

## Universe Filters

| Filter | Threshold | Rationale |
|--------|-----------|-----------|
| Market Cap | ≥ ₹500 Crore | Liquidity, institutional interest |
| Stock Price | ≥ ₹75 | Reduces penny stock noise |

---

## API Endpoints Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/app/run-pipeline` | POST | Run complete data pipeline |
| `/api/v1/ranking/top/{n}` | GET | Get top N stocks by score |
| `/api/v1/strategy/backtesting` | POST | Run backtest simulation |
| `/api/v1/investment/actions` | GET | Get pending trading actions |

---

## Key Design Decisions

1. **Friday-dated rankings**: Weekly rebalancing aligns with Friday close prices
2. **Buffer for swaps (25%)**: Reduces excessive churn; only swap if significantly better
3. **Dual stop-loss system**: ATR adapts to volatility, hard trailing locks in gains
4. **Cross-sectional ranking**: Stocks compete against each other daily, not historical self
5. **Separate databases**: Market data (`market_data.db`) vs personal investments (`personal.db`)

---

## Files Reference

| File | Purpose |
|------|---------|
| `indicators_service.py` | Calculate 30+ technical indicators |
| `percentile_service.py` | Cross-sectional percentile ranking |
| `score_service.py` | Weighted composite score calculation |
| `ranking_service.py` | Weekly average and ranking |
| `strategy_service.py` | Trading logic (buy/sell/swap) |
| `backtesting_new.py` | Historical simulation engine |

---

*Generated for strategy analysis and optimization.*
