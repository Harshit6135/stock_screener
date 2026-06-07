# Ranking System — Deep-Dive Documentation

> **Scope:** This document explains, in full detail, every step the screener executes from the moment raw market data is fetched from Kite until a final weekly rank (and a trading action) is produced. Each section corresponds to a real service/file in the codebase.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Phase 0 — Instrument Initialization (`InitService`)](#2-phase-0--instrument-initialization-initservice)
3. [Phase 1 — Market Data Ingestion (`MarketDataService`)](#3-phase-1--market-data-ingestion-marketdataservice)
4. [Phase 2 — Technical Indicator Calculation (`IndicatorsService`)](#4-phase-2--technical-indicator-calculation-indicatorsservice)
5. [Phase 3 — Factor Scoring (`FactorsService`)](#5-phase-3--factor-scoring-factorsservice)
6. [Phase 4 — Percentile Normalization (`PercentileService`)](#6-phase-4--percentile-normalization-percentileservice)
7. [Phase 5 — Composite Score & Penalties (`ScoreService`)](#7-phase-5--composite-score--penalties-scoreservice)
8. [Phase 6 — Weekly Ranking (`RankingService`)](#8-phase-6--weekly-ranking-rankingservice)
9. [Phase 7 — Trading Action Generation (`ActionGenerator` / `TradingEngine`)](#9-phase-7--trading-action-generation-actiongenerator--tradingengine)
10. [Database Schema Summary](#10-database-schema-summary)
11. [Configuration Reference](#11-configuration-reference)
12. [End-to-End Flow Diagram](#12-end-to-end-flow-diagram)

---

## 1. System Overview

The screener is a **multi-factor momentum scoring framework** designed for Indian equity markets (NSE/BSE). It converts raw OHLCV price data into a single **composite score** per stock per day, aggregates those scores into a **weekly rank**, and then uses the rank to automatically generate **BUY / SELL / SWAP** trading actions every Monday.

### Key Design Principles

| Principle | Detail |
|---|---|
| **Non-linear scoring** | RSI and EMA-distance use zone-based scoring, not raw values, to avoid rewarding extremes |
| **Percentile normalization** | All factor scores are cross-sectionally ranked against all stocks on the same day — a stock is only as good as its peers |
| **Penalty box** | Stocks below key EMAs or with ATR spikes are penalized rather than excluded, preserving partial information |
| **Hard exclusion** | Penny stocks (EMA-50 < ₹50) and illiquid stocks (avg turnover < ₹50L/day) are excluded with a 0× multiplier |
| **Weekly cadence** | Actions are generated once per week on Monday, using Friday's ranking |

---

## 2. Phase 0 — Instrument Initialization (`InitService`)

**File:** [`src/services/init_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/init_service.py)

This is a **one-time setup phase** (Day 0) that builds the instrument universe. It runs only when the system is first configured or the universe needs refreshing.

### Steps

```
NSE.csv + BSE.csv
       │
       ▼
1. fetch_and_merge_csvs()
   ├── Merge on ISIN
   ├── Keep only Indian stocks (ISIN starts with "IN")
   ├── Remove Mutual Funds, ETFs, Asset Management products
   └── Output: consolidated DataFrame [ISIN, NSE_SYMBOL, BSE_SYMBOL, NAME_OF_COMPANY]
       │
       ▼
2. fetch_yfinance_data()
   ├── Generate yfinance tickers (NSE_SYMBOL.NS preferred, fallback to BSE)
   ├── Fetch: marketCap, regularMarketPrice, sector, industry, floatShares
   └── Rate-limit safe: batch of 100, sleep 4s, 429 retry with 120s back-off
       │
       ▼
3. push_to_master() → master table
       │
       ▼
4. filter_stocks()
   ├── Remove stocks with Market Cap < ₹500 Cr  (MCAP_THRESHOLD = 500)
   └── Remove stocks with Price < ₹75            (PRICE_THRESHOLD = 75)
       │
       ▼
5. sync_with_kite()
   ├── Fetch live instruments from https://api.kite.trade/instruments
   ├── Match NSE EQ series first → BE series fallback → hyphen-split fallback
   ├── Cascade any token/series changes into market_data + indicators tables
   └── Populate instruments table: [instrument_token, exchange_token, tradingsymbol,
                                     name, exchange, series, marketcap, industry, sector]
```

### Critical Details

- **EQ vs BE series:** NSE lists some stocks in the Book Entry (BE) series. The system detects `SYMBOL-BE` in Kite instruments and strips the suffix so the internal `tradingsymbol` is always the base symbol (e.g. `HDFCBANK`).
- **Corporate action detection** (during daily updates): If the stored close price for the last date differs from the freshly fetched close for that same date, a split/bonus is assumed. All historical market data and indicators for that stock are deleted and re-fetched from scratch.

---

## 3. Phase 1 — Market Data Ingestion (`MarketDataService`)

**File:** [`src/services/marketdata_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/marketdata_service.py)

### Data Source

All price data comes from **Zerodha Kite API** (`KiteAdaptor.fetch_ticker_data`). The system stores OHLCV candles in the `market_data` table.

### Daily Update Flow

```
For each instrument in instruments table:
  ├── Get last stored date (market_data.get_latest_date_by_symbol)
  ├── If no data → use HISTORY_LOOKBACK = 2000 days back
  ├── If data exists → start from last stored date
  │
  ├── Corporate action check:
  │   ├── Fetch from Kite starting at last stored date
  │   ├── Compare stored close vs fetched close for the same date
  │   └── If mismatch → full refresh (delete + re-fetch)
  │
  ├── Historical fetch (> 2000 days):
  │   ├── Fetches backwards in 1900-day chunks
  │   ├── Deduplicates by date
  │   └── Sorts oldest-first before inserting
  │
  └── Rate limiting: max 3 req/sec (0.34s sleep per instrument)
```

### Output Table: `market_data`

| Column | Type | Notes |
|---|---|---|
| `tradingsymbol` | String | Primary key (with `date`) |
| `date` | Date | Trading day |
| `open` | Float | |
| `high` | Float | |
| `low` | Float | |
| `close` | Float | Adjusted close |
| `volume` | Integer | |
| `instrument_token` | Integer | Kite token |
| `exchange` | String | NSE / BSE |

---

## 4. Phase 2 — Technical Indicator Calculation (`IndicatorsService`)

**File:** [`src/services/indicators_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/indicators_service.py)  
**Config:** [`src/config/indicators_config.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/config/indicators_config.py)

For each instrument, indicators are computed **incrementally** — only new dates since the last indicator date are appended.

### Indicator Calculation Pipeline

```
For each instrument:
  1. Load market data from (last_indicator_date - 900 days) to yesterday
     [900-day lookback ensures EMA-200 is warm]
  
  2. Require minimum 200 rows (skip if less)
  
  3. Apply EMA Strategy (pandas_ta):
     └── EMA(200) — computed first on the full history for accuracy
  
  4. Truncate to (last_indicator_date - 365 days) [truncate_days = 365]
  
  5. Apply Momentum Strategy (pandas_ta):
     ├── EMA(50)
     ├── RSI(14)
     ├── ROC(10), ROC(20), ROC(60), ROC(125)
     ├── SMA(20)
     ├── Stochastic(14, 3, 3)
     ├── PPO(12, 26, 9)          ← Percentage Price Oscillator
     ├── MACD(12, 26, 9)
     ├── Bollinger Bands(20, 2)  ← BBU, BBL, BBM, BBB, BBP
     ├── ATR(14)
     ├── Volume SMA(20)          ← VOL_SMA_20
     └── EMA(20) of avg_turnover ← AVG_TURNOVER_EMA_20
  
  6. Apply Derived Strategy (pandas_ta):
     └── EMA(3) of RSI_14 → RSI_SIGNAL_EMA_3  [smoothed RSI]
  
  7. Calculate derived indicators:
     ├── price_vol_correlation  = Pearson corr(price_pct_change, volume)[10-day]
     ├── percent_b             = (close - BBL) / (BBU - BBL)
     ├── ema_50_slope          = (EMA50 - EMA50.shift(5)) / EMA50.shift(5)
     ├── distance_from_ema_200 = (close - EMA200) / EMA200
     ├── distance_from_ema_50  = (close - EMA50) / EMA50
     ├── risk_adjusted_return  = ROC_20 / (ATR_14 / close)
     ├── rvol                  = volume / VOL_SMA_20
     ├── atr_spike             = ATR_14 / rolling_mean(ATR_14, 20)
     ├── momentum_3m           = close.shift(5) / close.shift(65) - 1   [skip-week]
     └── momentum_6m           = close.shift(5) / close.shift(130) - 1  [skip-week]
  
  8. Filter to only new rows (> last_indicator_date)
  
  9. Bulk insert into indicators table
```

> **Why skip 5 days for momentum?** The 3m/6m momentum signals intentionally skip the most recent week (`shift(5)` instead of `shift(0)`) to avoid short-term mean-reversion noise — a common technique in academic momentum literature.

### Output Table: `indicators` (key columns used in scoring)

| Column | Formula / Source |
|---|---|
| `ema_50` | 50-day EMA of close |
| `ema_200` | 200-day EMA of close |
| `rsi_signal_ema_3` | 3-day EMA of RSI(14) — smoothed RSI |
| `ppo_12_26_9` | PPO line |
| `ppoh_12_26_9` | PPO histogram |
| `distance_from_ema_200` | (close − EMA200) / EMA200 |
| `ema_50_slope` | 5-day rate of change of EMA50 |
| `risk_adjusted_return` | ROC20 / (ATR14/close) |
| `atr_spike` | ATR14 / 20-day avg ATR |
| `rvol` | volume / 20-day avg volume |
| `price_vol_correlation` | 10-day Pearson corr |
| `percent_b` | %B Bollinger position |
| `bbb_20_2_2` | Bollinger Band Width |
| `momentum_3m` | Skip-week 3-month return |
| `momentum_6m` | Skip-week 6-month return |
| `avg_turnover_ema_20` | 20-day EMA of (close × volume) |

---

## 5. Phase 3 — Factor Scoring (`FactorsService`)

**File:** [`src/services/factors_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/factors_service.py)  
**Config:** [`src/config/strategies_config.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/config/strategies_config.py)  
**Utils:** [`src/utils/ranking_utils.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/utils/ranking_utils.py)

Five factors are computed. Each factor outputs a value roughly on a **0–100 scale** before percentile ranking.

---

### Factor 1: Trend (`factor_trend`)

**Intuition:** Is the stock trending upward at a healthy pace — not too weak, not extended to a dangerous level?

```
factor_trend = (0.4 × dist_score) + (0.6 × ema_slope_norm)
```

#### Sub-component A: `dist_score` — Goldilocks Scoring of `distance_from_ema_200`

Non-linear zone scoring. The "sweet spot" is 10–35% above the 200 EMA:

```
distance_from_ema_200 < 0          →  0        (below 200 EMA — bearish)
0%  ≤ distance ≤ 10%               →  70 → 85  (recovering, rising linearly)
10% < distance ≤ 35%               →  85 → 100 (SWEET SPOT: healthy uptrend)
35% < distance ≤ 50%               →  100 → 60 (extended, risk increasing)
distance > 50%                     →  60 → 0   (over-extended, decays to 0)
```

#### Sub-component B: `ema_slope_norm` — 50 EMA Slope Normalisation

```python
ema_50_slope = (EMA50 - EMA50.shift(5)) / EMA50.shift(5)
ema_slope_norm = ema_50_slope.clip(-5%, +5%) / 0.05 * 50 + 50
```

A slope of 0% maps to 50 (neutral). Positive slope → above 50. Clipped at ±5%.

**Weights:**
| Sub-factor | Weight |
|---|---|
| Distance from EMA-200 (Goldilocks) | **40%** |
| EMA-50 Slope | **60%** |

---

### Factor 2: Momentum (`factor_momentum`)

**Intuition:** Is the stock accelerating in the right direction with controlled RSI?

```
factor_momentum = (0.60 × rsi_score) + (0.20 × ppo_norm) + (0.10 × ppoh_norm) + (0.10 × pure_momentum)
```

#### Sub-component A: `rsi_score` — RSI Regime Scoring (non-linear)

```
RSI < 40            →  0           (oversold / weak)
40 ≤ RSI < 50       →  0 → 30      (recovering, rising linearly)
50 ≤ RSI ≤ 70       →  30 → 100    (SWEET SPOT: momentum zone)
70 < RSI ≤ 85       →  100 → 90    (slightly overbought, still ok)
RSI > 85            →  floors at 60 (overbought penalty, min 60)
```

> **Note:** The input is `rsi_signal_ema_3` — a 3-day EMA-smoothed RSI — to reduce noise.

#### Sub-component B: `ppo_norm` — PPO Line

```python
ppo_norm = ppo_12_26_9.clip(-5, +5) / 5 * 50 + 50
```
PPO = (EMA12 - EMA26) / EMA26 × 100. Maps ±5% PPO to 0–100.

#### Sub-component C: `ppoh_norm` — PPO Histogram

```python
ppoh_norm = ppoh_12_26_9.clip(-5, +5) / 5 * 50 + 50
```
The histogram (PPO - Signal) captures acceleration. Positive = gaining momentum.

#### Sub-component D: `pure_momentum` — Skip-Week Returns

```python
pure_momentum = ((momentum_3m + momentum_6m) / 2).clip(-50%, +50%) / 0.50 * 50 + 50
```

Averages 3-month and 6-month returns (both skip the most recent week to avoid reversal).

**Weights:**
| Sub-factor | Weight |
|---|---|
| RSI Regime Score (smoothed) | **60%** |
| PPO Line | **20%** |
| PPO Histogram | **10%** |
| Pure Momentum (3m + 6m avg) | **10%** |

---

### Factor 3: Risk Efficiency (`factor_efficiency`)

**Intuition:** Is the stock delivering returns proportional to the volatility risk it carries?

```python
risk_adj_norm = risk_adjusted_return.clip(-5, +5) / 5 * 50 + 50
spike_penalty = (atr_spike > 2.0).astype(float)
factor_efficiency = risk_adj_norm * (1 - spike_penalty * 0.5)
```

- `risk_adjusted_return = ROC_20 / (ATR_14 / close)` — a Sharpe-like ratio at the individual stock level.
- If `atr_spike > 2.0` (current ATR is more than 2× its 20-day average), efficiency is halved. This flags earnings events and news-driven volatility.

---

### Factor 4: Volume / Conviction (`factor_volume`)

**Intuition:** Is smart money participating? Are volume surges confirming the price move?

```python
rvol_norm   = rvol.clip(0, 3) / 3 * 100        # Relative volume, capped at 3× normal
corr_norm   = (vol_price_corr.clip(-1, 1) + 1) / 2 * 100  # Maps [-1,1] → [0,100]

factor_volume = (0.7 × rvol_norm) + (0.3 × corr_norm)
```

- `rvol` = today's volume / 20-day average volume. A value of 3× is max-scored.
- `price_vol_correlation` = 10-day Pearson correlation between daily price changes and volume. Positive = accumulation (price up on high volume), Negative = distribution.

**Weights:**
| Sub-factor | Weight |
|---|---|
| Relative Volume (RVOL) | **70%** |
| Price-Volume Correlation | **30%** |

---

### Factor 5: Structure (`factor_structure`)

**Intuition:** Is the stock breaking out of a proper base, or is it in a compressed / extended Bollinger Band pattern?

```python
b_score    = percent_b.apply(score_percent_b)
bw_change  = bandwidth.pct_change(5).fillna(0)
bw_score   = bw_change.clip(-0.5, +0.5) / 0.5 * 50 + 50

factor_structure = (0.5 × b_score) + (0.5 × bw_score)
```

#### %B Scoring (`score_percent_b`)

```
%B is NaN         →  50  (neutral)
%B < 0.5          →  20  (below midpoint — weak)
0.5 ≤ %B ≤ 0.7   →  20 → 60   (approaching upper band)
0.7 < %B ≤ 1.1   →  60 → 100  (near/at upper band — breakout zone)
%B > 1.1          →  floors at 70 (outside band — still strong but capped)
```

#### Bandwidth Change Score

```python
bbb_20_2_2  # Bollinger Band Width = (BBU - BBL) / BBM
bw_change   = 5-day % change in bandwidth
bw_score    = clipped to ±50% change, mapped to 0–100
```

Expanding bandwidth (breakout) scores above 50. Contracting bandwidth (squeeze) scores below 50.

**Weights:**
| Sub-factor | Weight |
|---|---|
| %B Position Score | **50%** |
| Bandwidth Expansion Score | **50%** |

---

## 6. Phase 4 — Percentile Normalization (`PercentileService`)

**File:** [`src/services/percentile_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/percentile_service.py)

### Purpose

After computing raw factor values (0–100 scale), a **cross-sectional percentile rank** is calculated across all stocks on the same date. This normalizes differences in the universe size and removes any absolute bias.

### Percentile Formula

```python
percentile = series.rank(pct=True) * 100
```

This is a non-parametric rank: `(count_below + 0.5 × count_equal) / N × 100`

- Robust to outliers
- Maps to 0–100; the median stock scores ~50 on every factor
- The best stock scores ~100; worst scores ~0

### `generate_percentile(date)` Flow

```
1. Fetch market data for all stocks on the given date
   → stocks_df: [tradingsymbol, close, volume]

2. Fetch indicators for all stocks on the given date
   → metrics_df: all indicator columns

3. Merge stocks_df + metrics_df on tradingsymbol

4. Compute avg_turnover = close × volume / 10,000,000  (in Cr)

5. Calculate raw factor scores via FactorsService.calculate_all_factors():
   → factor_trend, factor_momentum, factor_efficiency, factor_volume, factor_structure

6. For each factor, compute percentile_rank() across ALL stocks:
   → trend_percentile, momentum_percentile, efficiency_percentile,
      volume_percentile, structure_percentile

7. Delete existing percentiles for this date (idempotent re-calculation)

8. Bulk insert:
   [tradingsymbol, percentile_date, close,
    factor_trend, trend_percentile,
    factor_momentum, momentum_percentile,
    factor_efficiency, efficiency_percentile,
    factor_volume, volume_percentile,
    factor_structure, structure_percentile]
```

### Count Validation

On backfill, the service validates that the number of indicator rows for each new date does not differ from the previous day's count by more than **5%**. A larger swing indicates a data issue and raises a `ValueError`.

### Output Table: `percentile`

| Column | Range | Description |
|---|---|---|
| `factor_trend` | 0–100 | Raw trend factor score |
| `trend_percentile` | 0–100 | Cross-sectional rank |
| `factor_momentum` | 0–100 | Raw momentum factor score |
| `momentum_percentile` | 0–100 | Cross-sectional rank |
| `factor_efficiency` | 0–100 | Raw efficiency factor score |
| `efficiency_percentile` | 0–100 | Cross-sectional rank |
| `factor_volume` | 0–100 | Raw volume factor score |
| `volume_percentile` | 0–100 | Cross-sectional rank |
| `factor_structure` | 0–100 | Raw structure factor score |
| `structure_percentile` | 0–100 | Cross-sectional rank |

---

## 7. Phase 5 — Composite Score & Penalties (`ScoreService`)

**File:** [`src/services/score_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/score_service.py)

### Step-by-Step Internals (6-Step Pipeline)

```
[1/6] Fetch all percentiles with date > last_score_date   (incremental)
[2/6] Build percentiles DataFrame
[3/6] Fetch indicators for the same date range
[4/6] Calculate initial_composite_score (vectorized)
[5/6] Merge indicators + apply soft penalties
[6/6] Bulk insert results into score table
```

### Step 4: Initial Composite Score Formula

```
initial_composite_score =
    0.30 × trend_percentile
  + 0.25 × momentum_percentile
  + 0.20 × efficiency_percentile
  + 0.15 × volume_percentile
  + 0.10 × structure_percentile
```

**All weights sum to 1.0** (validated at startup via `StrategyParameters.__post_init__`).

| Factor | Weight | Rationale |
|---|---|---|
| Trend | **30%** | Dominant regime filter — in-trend stocks are the primary focus |
| Momentum | **25%** | Price acceleration and RSI health confirm the move |
| Risk Efficiency | **20%** | Quality gate — rewarding risk-adjusted, not raw, returns |
| Conviction (Volume) | **15%** | Smart money confirmation |
| Structure | **10%** | Breakout confirmation via Bollinger position |

### Step 5: Soft Penalty Box

After scoring, the `initial_composite_score` is multiplied by a `penalty` factor (1.0 = no penalty, 0.0 = full exclusion):

```python
final_composite_score = initial_composite_score × penalty
```

Penalties are applied **additively** (multiplied together), evaluated in this order:

| Condition | Multiplier | Label |
|---|---|---|
| `EMA_200 > close` (below 200 EMA) | × 0.5 | `below_ema_200` |
| `EMA_50 > close` (below 50 EMA) | × 0.7 | `below_ema_50` |
| `atr_spike > 2.0` (volatility spike) | × 0.8 | `atr_spike` |
| `EMA_50 < ₹50` (penny stock) | × 0.0 | `penny_stock` **HARD EXCLUSION** |
| `avg_turnover_ema_20 < ₹50L` | × 0.0 | `low_turnover` **HARD EXCLUSION** |

> **Example:** A stock below both EMAs has: 1.0 × 0.5 × 0.7 = **0.35** penalty.  
> If `initial_composite_score = 70`, `composite_score = 70 × 0.35 = 24.5`.

### `penalty_reason` Column

A semicolon-separated string of active penalties is stored for transparency, e.g.:  
`"below_ema_200; below_ema_50"`

### Output Table: `score`

| Column | Notes |
|---|---|
| `tradingsymbol` | Primary key (with `score_date`) |
| `score_date` | Same as `percentile_date` |
| `initial_composite_score` | Before penalties |
| `penalty` | Multiplier (0.0 to 1.0) |
| `penalty_reason` | Human-readable penalty labels |
| `composite_score` | `initial_composite_score × penalty` — the final daily score |

---

## 8. Phase 6 — Weekly Ranking (`RankingService`)

**File:** [`src/services/ranking_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/ranking_service.py)

### Why Weekly?

Daily scores can be noisy (news, earnings). Averaging a full trading week (Mon–Fri) smooths noise and produces a more stable rank for a once-a-week rebalancing system.

### Algorithm

```
1. Find last_ranking_date (max date in ranking table)
2. Find last_score_date (max date in score table)

3. Determine starting Friday:
   ├── If ranking table is empty → find first score date, compute its Friday
   └── If ranking exists → start from (last_ranking_date's Friday + 7 days)

4. For each Friday (current_friday) up to end_friday:
   ├── Skip if current_friday >= today (week not yet complete)
   │
   ├── week_start = current_friday - 6 days  [Monday of that week]
   │
   ├── Fetch all composite_scores for [week_start, current_friday]
   │
   ├── Group by tradingsymbol → average composite_score across Mon–Fri
   │
   ├── Sort by avg composite_score DESCENDING
   │
   ├── Assign rank 1 = highest score, 2 = second highest, ...
   │
   └── Store [tradingsymbol, ranking_date=current_friday, composite_score, rank]

5. Bulk insert all weeks in a single transaction
```

### Key Properties

- **`ranking_date` = Friday** of the week (not Monday)
- **Rank 1 = best stock** (highest average composite score)
- **Incremental**: only processes weeks after the last ranked Friday
- **`recalculate_all_rankings()`**: deletes everything and runs from scratch — use when scores change

### Output Table: `ranking`

| Column | Notes |
|---|---|
| `tradingsymbol` | Primary key (with `ranking_date`) |
| `ranking_date` | Always a Friday |
| `composite_score` | Avg composite score across the week |
| `rank` | Integer, 1 = best |

---

## 9. Phase 7 — Trading Action Generation (`ActionGenerator` / `TradingEngine`)

**Files:**  
- [`src/services/action_generator.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/action_generator.py)  
- [`src/services/trading_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/trading_service.py)

### Entry Point: `generate_actions(action_date)`

Called every Monday. Uses the **previous Friday's ranking** as the signal.

```
action_date = Monday
data_date   = get_prev_friday(action_date)  [Friday of last week]
```

### Decision Flow

```
Step 1: Load top-N stocks from ranking table for data_date
        top_n = ranking_repo.get_top_n_by_date(max_positions, data_date)
        [max_positions is configurable, default = 20 from TOP_N_RANKINGS]

Step 2: Load portfolio context
        ├── current_holdings (InvestmentRepository)
        ├── total_capital (realized + unrealized)
        └── remaining_capital (available cash)

Step 3: Load market context for data_date (Friday closes)
        ├── Prices for all holdings and candidates
        └── EMA-50 values for pyramid eligibility checks

Step 4: TradingEngine.generate_decisions()  [pure, stateless]
        ├── PHASE 1 — SELL decisions:
        │   For each holding:
        │   ├── If current_price < stop_loss → SELL (stoploss hit)
        │   └── If composite_score < exit_threshold (40.0) → SELL (score degraded)
        │
        └── PHASE 2 — Unified Candidate Loop:
            For each candidate (sorted by score, best first):
            ├── Case A: Already held + pyramiding enabled:
            │   └── If stop_loss >= entry_price AND EMA-50 >= avg_price → PYRAMID_ADD
            ├── Case B: Not held + vacancies > 0:
            │   └── BUY (vacancy fill)
            └── Case C: Not held + no vacancy + score > swap_buffer × weakest_holding.score:
                └── SWAP (sell weakest, buy candidate)
                    [swap_buffer = 1 + buffer_percent, default ~1.25]

Step 5: Execute Phase — Sell → Pyramid → Buy (in order)

  Phase 1 — SELL:
    ├── Get Friday close price for each sell symbol
    ├── Create SellActionResult (units, capital_released, realized_gain)
    └── Add released capital back to remaining_capital

  Phase 2 — PYRAMID_ADD:
    └── Size at pyramid_fraction% of total_capital (PyramidConfig)

  Phase 3 — BUY:
    ├── For each top_n candidate with BUY or SWAP-BUY decision:
    │   ├── Look up Friday close price
    │   ├── Get ATR for position sizing:
    │   │   ├── Risk = ATR × sl_multiplier
    │   │   ├── units = floor(risk_budget / risk_per_unit)
    │   │   └── stop_loss = prev_close - (ATR × sl_multiplier)
    │   └── Create BuyActionResult
    │
    └── Backfill: if slots remain after primary buys,
        fill from top_n list in order

Step 6: Persist all actions (de-duplicate by date + symbol)
        Actions with units = 0 saved as "Pending" (capital-constrained)
```

### ATR-Based Position Sizing

```python
risk_per_unit  = ATR × sl_multiplier
units          = floor(risk_budget / risk_per_unit)
capital_needed = units × current_price
stop_loss      = current_price - risk_per_unit
hard_sl_price  = stop_loss × (1 - hard_sl_percent)  [e.g., 3% below SL]
```

Where `risk_budget = total_capital × risk_pct_per_trade`.

### Mid-Week Stop-Loss Check

On non-Monday trading days, `check_daily_stoploss(day)` runs:
- Compares each holding's close price against `current_sl`
- If `close < current_sl` → generates a `Pending SELL` for the **next business day's open**
- Optionally advances existing pending BUY orders to fill new vacancies (if `mid_week_buy=True`)
- Stale buy orders (price has risen > 5% above signal price) are **skipped**

---

## 10. Database Schema Summary

```
instruments     ← universe of stocks to track
      │
      ▼
market_data     ← daily OHLCV (raw price data from Kite)
      │
      ▼
indicators      ← daily technical indicators per stock
      │
      ▼
percentile      ← daily factor scores + percentile ranks per stock
      │
      ▼
score           ← daily composite score (with penalties)
      │
      ▼
ranking         ← weekly average score + rank (every Friday)
      │
      ▼
actions         ← BUY / SELL / SWAP orders (Pending → Executed)
      │
      ▼
investments     ← live portfolio holdings
```

---

## 11. Configuration Reference

**File:** [`src/config/strategies_config.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/config/strategies_config.py)

### `StrategyParameters` — Top-Level Factor Weights

| Parameter | Default | Description |
|---|---|---|
| `trend_strength_weight` | **0.30** | Weight of trend percentile |
| `momentum_velocity_weight` | **0.25** | Weight of momentum percentile |
| `risk_efficiency_weight` | **0.20** | Weight of efficiency percentile |
| `conviction_weight` | **0.15** | Weight of volume percentile |
| `structure_weight` | **0.10** | Weight of structure percentile |
| `atr_threshold` | **2.0** | ATR spike ratio to trigger soft penalty |
| `min_price` | **₹50.0** | EMA-50 below this = hard exclusion |
| `min_turnover` | **₹0.5 Cr/day** | Avg turnover below this = hard exclusion |

### Sub-Factor Weights

| Parameter | Default | Factor |
|---|---|---|
| `trend_distance_200_weight` | 0.40 | Trend |
| `trend_slope_weight` | 0.60 | Trend |
| `momentum_rsi_weight` | 0.60 | Momentum |
| `momentum_ppo_weight` | 0.20 | Momentum |
| `momentum_ppoh_weight` | 0.10 | Momentum |
| `pure_momentum_weight` | 0.10 | Momentum |
| `rvolume_weight` | 0.70 | Volume |
| `price_vol_corr_weight` | 0.30 | Volume |
| `percent_b_weight` | 0.50 | Structure |
| `bollinger_width_weight` | 0.50 | Structure |

### `GoldilocksConfig` — Trend Zone Boundaries

| Zone | Distance Range | Score Range |
|---|---|---|
| Below EMA | < 0% | 0 |
| Zone 1 | 0–10% | 70–85 |
| Zone 2 (Sweet Spot) | 10–35% | 85–100 |
| Zone 3 (Extended) | 35–50% | 100→60 |
| Zone 4 (Over-extended) | > 50% | 60→0 |

### `RSIRegimeConfig` — Momentum Zone Boundaries

| Zone | RSI Range | Score Range |
|---|---|---|
| Weak | < 40 | 0 |
| Recovering | 40–50 | 0–30 |
| Sweet Spot | 50–70 | 30–100 |
| Slightly overbought | 70–85 | 100–90 |
| Overbought | > 85 | floors at 60 |

### `app_config.py` — System-Level Parameters

| Parameter | Default | Description |
|---|---|---|
| `MCAP_THRESHOLD` | 500 Cr | Minimum market cap for universe |
| `PRICE_THRESHOLD` | ₹75 | Minimum stock price for universe |
| `HISTORY_LOOKBACK` | 2000 days | Days of history to fetch on first run |
| `TOP_N_RANKINGS` | 20 | Max positions in portfolio |
| `DEFAULT_INITIAL_SL` | 3% | Initial stop-loss percentage |

---

## 12. End-to-End Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                      DAILY PIPELINE (Automated)                     │
└─────────────────────────────────────────────────────────────────────┘

[Kite API]
    │
    │  OHLCV candles (daily)
    ▼
┌──────────────────┐
│  MarketDataService│  → INSERT into market_data table
│  (Phase 1)       │    [open, high, low, close, volume, date, symbol]
└────────┬─────────┘
         │
         │  Market data for each stock (up to 900+ days of history)
         ▼
┌──────────────────┐
│ IndicatorsService │  → UPSERT into indicators table
│  (Phase 2)       │    Computes: EMA-50/200, RSI, PPO, ATR, RVOL,
└────────┬─────────┘    Bollinger Bands, %B, momentum_3m/6m, slopes, etc.
         │
         │  Indicator rows for the new date
         ▼
┌──────────────────┐
│ FactorsService   │  (called inside PercentileService)
│  (Phase 3)       │  Raw factor values per stock (0-100 approx.):
└────────┬─────────┘  factor_trend, factor_momentum, factor_efficiency,
         │            factor_volume, factor_structure
         │
         │  All stocks' raw factor values on this date
         ▼
┌──────────────────┐
│PercentileService │  → DELETE + REINSERT into percentile table
│  (Phase 4)       │    Cross-sectional rank across ALL stocks:
└────────┬─────────┘    trend_pct, momentum_pct, efficiency_pct,
         │              volume_pct, structure_pct (0-100)
         │
         │  Percentile rows for each stock on each new date
         ▼
┌──────────────────┐
│  ScoreService    │  → BULK INSERT into score table
│  (Phase 5)       │  (1) initial_composite_score = weighted sum of percentiles
└────────┬─────────┘  (2) merge indicators for penalty checks
         │            (3) apply soft/hard penalty multipliers
         │            (4) composite_score = initial × penalty
         │
         │  Daily composite scores for every stock

┌─────────────────────────────────────────────────────────────────────┐
│                      WEEKLY PIPELINE (Every Friday)                 │
└─────────────────────────────────────────────────────────────────────┘

         ▼
┌──────────────────┐
│  RankingService  │  → BULK INSERT into ranking table
│  (Phase 6)       │  For the just-completed Mon-Fri week:
└────────┬─────────┘  (1) average composite_score per stock
         │            (2) sort descending
         │            (3) rank = 1 (best) to N (worst)
         │            (4) ranking_date = Friday

┌─────────────────────────────────────────────────────────────────────┐
│                      WEEKLY ACTION (Every Monday)                   │
└─────────────────────────────────────────────────────────────────────┘

         │  Top-N stocks by rank on previous Friday
         ▼
┌──────────────────┐
│  TradingEngine   │  Pure stateless decision logic:
│  (Phase 7a)      │  SELL (SL hit / score < 40) →
└────────┬─────────┘  BUY (vacancy) → SWAP (stronger displaces weaker)
         │
         ▼
┌──────────────────┐
│ ActionGenerator  │  → INSERT into actions table
│  (Phase 7b)      │    For each decision: ATR-sized BUY or SELL
└──────────────────┘    with stop_loss, hard_sl_price, units, capital
```

---

*Last updated: 2026-06-07 — Generated from source analysis of `stocks_screener_v2`.*
