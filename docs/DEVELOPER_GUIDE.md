# Developer Guide — Stock Screener V2

> **Last Updated:** 2026-07-12  
> For a new developer joining the project. Read top-to-bottom in one sitting.

---

## 1. What is this?

A systematic, rules-based **momentum stock screener and portfolio manager** for
Indian equities (NSE/BSE). It:

1. Fetches daily OHLCV data from Kite Connect (Zerodha)
2. Calculates 15+ technical indicators with `pandas_ta`
3. Cross-sectionally ranks every stock by a multi-factor composite score
4. Generates weekly BUY / SELL / PYRAMID trade decisions
5. Tracks a live portfolio and lets you run historical backtests

**Tech stack:** Python 3.13, Flask, Flask-Smorest, SQLAlchemy, SQLite, pandas, pandas_ta, Kite Connect API, yfinance.

---

## 2. Running it locally

```bash
poetry install
cp local_secrets.example.py local_secrets.py   # add Kite API key/secret
make db-init && make db-upgrade                 # create SQLite tables
make run                                        # Flask dev server -> http://127.0.0.1:5000
# Swagger UI -> http://127.0.0.1:5000/api/v1/swagger-ui
```

---

## 3. Repository layout

```
src/
+-- adaptors/          # Thin wrappers for external services (Kite Connect)
+-- api/v1/routes/     # Flask blueprints — HTTP only, no business logic
+-- config/            # Static configuration dataclasses
+-- models/            # SQLAlchemy ORM models (table schema)
+-- repositories/      # All DB queries live here — no raw SQL in services
+-- schemas/           # Marshmallow request/response validation schemas
+-- services/          # Business logic — the main application code
+-- utils/             # Pure, stateless helper functions
```

The strict rule: **each layer only imports from layers below it**.
Routes -> Services -> Repositories -> Models. No layer-skipping.

---

## 4. Data pipeline — step by step

The full pipeline is triggered via `POST /api/v1/app/run-pipeline`.
Each step can also be called individually.

```
Market Data -> Indicators -> Percentiles -> Scores -> Rankings
```

### 4.1 InitService (`init_service.py`)

**Runs once (Day 0)** or when updating the stock universe.

- Downloads NSE/BSE instrument lists from Kite Connect
- Filters by price (PRICE_THRESHOLD) and market cap (MCAP_THRESHOLD)
- Fetches historical OHLCV from yfinance for the filtered universe
- Populates `instruments`, `master`, `market_data` tables

### 4.2 MarketDataService (`marketdata_service.py`)

Fetches **daily OHLCV** from Kite Connect for all active instruments.

- `update_latest_data_for_all(historical=False)` — incremental update (since last record) or full backfill

Data is stored in `market_data` table keyed by `(instrument_token, date)`.

### 4.3 IndicatorsService (`indicators_service.py`)

Calculates 20+ technical indicators using `pandas_ta` studies defined in
`config/indicators_config.py`.

Key indicators written to the `indicators` table:

| Column | Meaning |
|--------|---------|
| `ema_50`, `ema_200` | Trend EMAs |
| `rsi_14` | 14-period RSI |
| `ppo_12_26_9`, `ppoh_12_26_9` | PPO momentum + histogram |
| `atrr_14` | ATR% (normalized) |
| `atr_spike` | ATR spike detection flag |
| `rvol` | Relative volume vs 20-day average |
| `roc_10/20/60/125` | Rate of change at multiple lookbacks |
| `avg_turnover_ema_20` | Liquidity proxy |
| `percent_b`, `bbb_20_2_2` | Bollinger Band position + width |
| `price_vol_correlation` | Trend quality measure |

### 4.4 PercentileService (`percentile_service.py`)

Cross-sectionally ranks every active stock by each factor **on every Friday**.

- Groups all stocks on a given Friday
- Ranks each within the group using `percentile_rank()` -> 0-100
- Writes to `percentile` table with `(instrument_token, percentile_date)` key

Two strategy variants exist (`StrategyParameters` and `Strategy2Parameters`).

### 4.5 FactorsService (`factors_service.py`)

Applies **non-linear transformations** to raw percentile ranks:

- **Goldilocks trend score** — rewards stocks at 10-35% above EMA200.
  Too close = no trend; too far = overextended. Config: `GoldilocksConfig`.
- **RSI regime score** — rewards RSI in the 50-70 zone.
  Below 50 = weak momentum; above 70 = overbought risk. Config: `RSIRegimeConfig`.

### 4.6 ScoreService (`score_service.py`)

Combines factor scores using **configurable weights** from `StrategyParameters`:

```
composite_score = (
    trend_strength    x trend_weight
  + momentum_velocity x momentum_weight
  + risk_efficiency   x efficiency_weight
  + volume_conviction x volume_weight
  + price_structure   x structure_weight
)
```

Applies **soft penalties** (score reduction, not zero-out) for:
- Low liquidity (avg_turnover_ema_20 < threshold)
- ATR spike (abnormally high volatility)
- Very low Bollinger Band width (consolidating, no trend)

Writes to `composite_score` table.

### 4.7 RankingService (`ranking_service.py`)

Aggregates daily composite scores into a **weekly rank** anchored to Friday.

- For each Friday, computes the average composite score across the week
- Ranks all stocks in descending order
- Writes `composite_score`, `rank` to the `ranking` table

`get_prev_friday(date)` is used everywhere to normalize any date to its
preceding Friday for consistent lookups.

---

## 5. Trading engine

### 5.1 TradingService (`trading_service.py`)

Top-level weekly trading orchestration. Called via `POST /api/v1/actions/generate`.

For a given `action_date` (Monday open):
1. Calls `ActionGenerator` -> produces Pending actions
2. Calls `ActionLifecycle` -> approves/rejects actions
3. Calls `ActionProcessor` -> updates holdings based on approved actions
4. Calls `InvestmentService.get_summary()` -> writes weekly portfolio summary

### 5.2 ActionGenerator (`action_generator.py`)

Generates the three action types in strict order:

**Phase 1 — SELLs**
- Stop-loss breached: weekly low < `current_sl` -> SELL (reason: `stoploss`)
- Score degraded below `exit_threshold` -> SELL (reason: `score_exit`)
- Concentration limit: holding > `max_position_percent` -> SELL (reason: `concentration`)

**Phase 2 — PYRAMIDs (add to winners)**
- In top rankings + existing holding + score above threshold -> `pyramid_add`
- Fraction of capital controlled by `PyramidConfig.pyramid_fraction`

**Phase 3 — BUYs**
- Top-N ranked stocks not already held, not just sold -> BUY
- Budget constrained by remaining capital after sells and pyramids

All actions are written to `actions` table with `status="Pending"`.

### 5.3 ActionLifecycle (`action_lifecycle.py`)

Transitions Pending -> Approved | Rejected.

**Phase 1 — Sells** (always approved at Monday open price)
- Looks up Monday open from `market_data`
- Updates action with `execution_price`, `status="Approved"`
- Adds sell proceeds back to `remaining_capital`

**Phase 2 — Buys** (capital-gated)
- Re-sizes each buy at the actual Monday open price
- Uses `calculate_position_size()` for ATR-based sizing
- Skips if budget exhausted (units == 0)
- Updates action with `execution_price`, `units`, `capital`, `status="Approved"`

### 5.4 ActionProcessor (`action_processor.py`)

Materializes approved actions into the holdings table.

- For sells: removes the holding record
- For buys: inserts a new holding with `entry_price`, `entry_sl`, `atr`, etc.
- For pyramids: updates existing holding — increases units, recalculates `avg_price`
- Writes stop-loss: `entry_sl = entry_price - (sl_multiplier x atr)`

### 5.5 InvestmentService (`investment_service.py`)

Portfolio accounting and reporting layer.

| Method | What it does |
|--------|--------------|
| `get_portfolio_summary()` | Current holdings value, unrealized gain, XIRR |
| `get_summary(week_holdings, sold)` | Weekly portfolio snapshot for summary table |
| `get_trade_journal()` | FIFO-matched buy/sell pairs with PnL |
| `update_holding(symbol, date)` | Refresh current price + ATR trailing stop |
| `sync_prices()` | Batch price refresh for all holdings |
| `ensure_capital_events_seeded()` | Auto-seed capital_events from config if empty |
| `add_capital_event()` | Record infusion / withdrawal |

**Capital arithmetic (first principles):**

```
total_capital     = sum(capital_events)      # all infusions ever
cost_basis        = sum(avg_price x units)   # all open positions
remaining_capital = total_capital - cost_basis
```

remaining_capital is recomputed each cycle — not carried forward from a column.

---

## 6. Backtesting engine

### Overview (`backtesting_service.py`)

`WeeklyBacktester` replays the full trading engine over a historical date range.

It **injects a separate SQLite DB** (per run, inside `backtest_history/<run_label>/`)
into the same `ActionGenerator`, `ActionLifecycle`, `ActionProcessor`, and
`InvestmentService`. This means **identical logic** for live and backtest.

Prerequisite: the main DB must already have `market_data`, `indicators`,
and `ranking` rows for the simulation period.

### Run modes

| Mode | Flag | Meaning |
|------|------|---------|
| Weekly only | `check_daily_sl=False` | Stop-loss checked once per week |
| Daily SL | `check_daily_sl=True` | Stop-loss checked each trading day |
| Mid-week buy | `mid_week_buy=True` | Buys approved mid-week on Thursday open |

### Backtest report sections

1. Configuration params
2. Performance metrics (CAGR, XIRR, Sharpe, Sortino, Calmar, drawdown)
3. Year-on-Year returns
4. Trade statistics (win rate, profit factor, expectancy)
5. Open positions at backtest end
6. Full trade log

> All PnL figures are **gross** (pre-cost, pre-tax). No deductions applied.

---

## 7. Utilities

All utils are **pure functions** — no DB access, no side effects.

### `sizing_utils.py`

`calculate_position_size(atr, current_price, total_capital, remaining_capital, config)`

ATR-based risk-parity sizing:
```
risk_per_unit = atr x sl_multiplier
units = (total_capital x risk_threshold) / risk_per_unit
```
Capped by `max_position_percent`, `remaining_capital`, and `min_position_percent`.

### `stoploss_utils.py`

`calculate_atr_trailing_stop(current_price, current_atr, stop_multiplier, previous_stop)`

ATR trailing stop — only moves **up** (ratchet):
```
new_stop      = current_price - (stop_multiplier x atr)
effective_stop = max(new_stop, previous_stop)
```

### `date_utils.py`

Loads NSE/BSE holidays from CSV on import.

| Function | Use |
|----------|-----|
| `get_prev_friday(date)` | Resolve any date to the preceding Friday |
| `is_holiday(date)` | Check weekend or NSE holiday |
| `get_business_days(start, end)` | List of trading days |
| `get_next_business_day(date)` | Skip weekends + holidays forward |
| `get_previous_business_day(date)` | Skip weekends + holidays backward |
| `get_week_starts(start, end)` | First trading day of each Mon-Fri week |

### `ranking_utils.py`

| Function | Use |
|----------|-----|
| `percentile_rank(series)` | Simple percentile rank 0-100 |
| `rsi_regime_score(rsi)` | RSI -> 0-100 regime score |
| `goldilocks_score(distance)` | EMA distance -> 0-100 trend score |

### `fifo_matcher.py`

`FIFOTradeTracker.from_actions(all_actions)` — matches sells to earliest
unmatched buys (FIFO). Returns `MatchedTrade` list with pnl, return_pct,
days_held. Used by trade journal and backtest report.

### `metrics.py`

`calculate_all_metrics(equity_curve, trades, initial_value, years)` returns:

| Metric | Formula |
|--------|---------|
| `cagr` | (final/initial)^(1/years) - 1 |
| `xirr` | Newton's method on cashflows |
| `sharpe_ratio` | Mean / Std of weekly returns x sqrt(52) |
| `sortino_ratio` | Mean / Downside std x sqrt(52) |
| `max_drawdown` | Max peak-to-trough drop |
| `win_rate` | % of trades with PnL > 0 |
| `profit_factor` | Total wins / Total losses |
| `expectancy` | Average PnL per trade |

### `database_manager.py`

`DatabaseManager` creates isolated SQLAlchemy sessions bound to a specific
SQLite file. Used by the backtesting engine for DB injection.

---

## 8. Configuration system

### Static config (`src/config/`)

All parameters are **Python dataclasses with defaults**.

| File | Class | Key settings |
|------|-------|-------------|
| `strategies_config.py` | `StrategyParameters` | Factor weights (trend 30%, momentum 25%, efficiency 15%, volume 15%, structure 15%) |
| `strategies_config.py` | `Strategy2Parameters` | Alternative weights |
| `strategies_config.py` | `GoldilocksConfig` | EMA distance zones |
| `strategies_config.py` | `RSIRegimeConfig` | RSI regime zones |
| `pyramid_config.py` | `PyramidConfig` | `pyramid_fraction` |
| `app_config.py` | constants | MCAP_THRESHOLD, PRICE_THRESHOLD, TOP_N_RANKINGS |
| `indicators_config.py` | `INDICATOR_REGISTRY` | pandas_ta study definitions |

### Runtime config (DB table)

`config` table stores per-strategy trading parameters editable via API:
`initial_capital`, `max_positions`, `risk_threshold`, `sl_multiplier`,
`buffer_percent`, `exit_threshold`, `min_position_percent`, `atr_fallback_percent`

Accessed via `ConfigRepository.get_config(config_name)`.

---

## 9. Repository pattern

Every service receives its repositories via `__init__`. For backtesting, an
isolated `session` is injected:

```python
# Live trading
inv_service = InvestmentService()

# Backtesting — isolated DB
session = DatabaseManager(backtest_db_path).create_session()
inv_service = InvestmentService(session=session)
```

All repository classes pattern:
```python
class FooRepository:
    def __init__(self, session=None):
        self.session = session or db.session
```

---

## 10. API layer — 12 blueprints

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| `init_bp` | `/api/v1/init` | Stock universe initialization |
| `app_bp` | `/api/v1/app` | Pipeline orchestration, cleanup, recalculate |
| `config_bp` | `/api/v1/config` | Read/write trading config |
| `instruments_bp` | `/api/v1/instruments` | Instrument list CRUD |
| `marketdata_bp` | `/api/v1/market_data` | OHLCV data endpoints |
| `indicators_bp` | `/api/v1/indicators` | Indicator data endpoints |
| `percentile_bp` | `/api/v1/percentile` | Percentile rank data |
| `score_bp` | `/api/v1/score` | Composite score data |
| `ranking_bp` | `/api/v1/ranking` | Ranking data |
| `actions_bp` | `/api/v1/actions` | Generate/view/approve actions |
| `investment_bp` | `/api/v1/investment` | Portfolio summary, holdings, trades |
| `backtest_bp` | `/api/v1/backtest` | Run backtest, view results |

---

## 11. Database

### Three SQLite databases

| Database | Bind key | Purpose |
|----------|----------|---------|
| `main.db` | `main` | Market data, indicators, percentiles, scores, rankings |
| `personal.db` | `personal` | Actions, holdings, portfolio summary, capital events |
| `backtest.db` | `backtest` | Per-run isolated copy of personal DB |

Multi-bind configured in `flask_config.py` via `SQLALCHEMY_BINDS`.

---

## 12. Logging and SSE

`setup_logger(name)` writes to stdout and to `sse_log_queue`.

`GET /api/v1/app/logs/stream` drains `sse_log_queue` as Server-Sent Events.
Open this **before** triggering the pipeline to watch real-time progress.

---

## 13. Key design decisions

| Decision | Rationale |
|----------|----------|
| Separate backtest DB | Isolates simulation; no production data touched |
| Same services for live + backtest | Session injection = 100% logic parity |
| Friday-anchored lookups | Weekly rank stability via `get_prev_friday()` |
| Three-phase action generation | SELLs free capital first; order strictly matters |
| Soft penalties, not hard zero | Avoids cliff-edge rank drops on threshold crossings |
| Capital from first principles | remaining_capital recomputed; not from summary column |
| Repository pattern | Separates logic from DB; enables easy session injection |
| Pure utility functions | Stateless utils are easy to unit-test in isolation |
| No cost/tax deductions | PnL is gross. Simplifies accounting and backtesting. |

---

## 14. New developer checklist

- [ ] Read this file top-to-bottom
- [ ] Run `make run` and open Swagger UI
- [ ] Read `src/config/strategies_config.py` — understand all weights
- [ ] Trace one pipeline run: `POST /api/v1/app/run-pipeline` with SSE stream open
- [ ] Read `action_generator.py` — the three action phases
- [ ] Read `action_lifecycle.py` — capital-gated approval logic
- [ ] Run a short backtest via Swagger UI and read the text report
- [ ] Read `docs/STRATEGY.md` for full factor-by-factor rationale
