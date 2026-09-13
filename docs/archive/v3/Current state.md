# Comprehensive Codebase Analysis & Architecture Documentation

> Historical analysis of the pre-v3 application. The Flask-Smorest routes,
> SQLAlchemy binds, dashboard, and legacy strategy services described below
> are no longer present in the current backend-only working tree. For actual
> deployment and remaining gaps, use [README](../README.md) and the
> [remediation review](DESIGN_IMPLEMENTATION_GAP_REVIEW.md).

## Executive Summary

The **Stock Screener v3.0.0** codebase is an enterprise-grade, multi-factor momentum screening, portfolio management, and backtesting system designed specifically for Indian Equities (NSE & BSE).

The codebase is built on **Python 3.13** using **Flask 3.1**, **Flask-Smorest (OpenAPI 3.0.3)**, **Flask-SQLAlchemy 3.1**, **pandas**, **pandas_ta**, and **Waitress**. It implements a complete end-to-end data pipeline, multi-factor quantitative ranking engines, capital-gated execution logic, first-principles portfolio accounting, and an isolated backtesting simulation engine.

---

## Architecture Overview

```mermaid
graph TD
    subgraph Data Sources
        Kite[Zerodha Kite Connect API / WebSocket]
        YF[yfinance API]
        Bench[Nifty 500 Index Source]
    end

    subgraph Data Pipeline Services
        Init[InitService - Day 0 Import & Filter]
        MD[MarketDataService - Daily OHLCV & Corporate Actions]
        Ind[IndicatorsService - pandas_ta & Derived Indicators]
        Perc[PercentileService - Cross-Sectional Ranking 0-100]
        Score[ScoreService - Composite Scoring & Penalties]
        Rank[RankingService - Weekly Rank & Score Averaging]
    end

    subgraph Trading & Execution Services
        Engine[TradingEngine - Decision Matrix]
        Gen[ActionGenerator - Buy/Sell/Swap Action Builder]
        Life[ActionLifecycle - Monday Open Approval & Resizing]
        Proc[ActionProcessor - Portfolio Holdings & Summary Upsert]
    end

    subgraph Portfolio & Backtest
        Inv[InvestmentService - Accounting, XIRR, FIFO Journal]
        Back[WeeklyBacktester - Simulation Engine]
        Hist[BacktestHistoryRepository - File & DB Persistence]
    end

    Kite --> MD
    YF --> Init
    Bench --> Ind
    Init --> MD
    MD --> Ind
    Ind --> Perc
    Perc --> Score
    Score --> Rank
    Rank --> Engine
    Engine --> Gen
    Gen --> Life
    Life --> Proc
    Proc --> Inv
    Rank --> Back
    Back --> Hist
```

---

## Detailed Component Analysis

### 1. Application Server & Entry Points (`run.py`, `pyproject.toml`)
- **Web Server**: Waitress WSGI server listening on `0.0.0.0:5000` with 3 worker threads (supporting SSE logging, pipeline execution, and dashboard UI concurrently) and a 600-second channel timeout.
- **Request Logging**: Wrapped with `paste.translogger.TransLogger`.
- **API Documentation**: Automatic OpenAPI 3.0.3 documentation hosted via Swagger UI (`/swagger-ui`) and ReDoc (`/redoc`).
- **Web Dashboard Routes**: `/` (renders `dashboard.html`), `/actions` (renders `actions.html`), `/backtest` (redirects to dashboard `#backtest`).

---

### 2. Multi-Database Architecture (`db.py`, `src/config/flask_config.py`, `src/utils/database_manager.py`)

The application utilizes 3 distinct SQLite database binds managed by SQLAlchemy:

1. **Default Database (`market_data.db`)**: Stores market-wide data:
   - `master_stocks`: Complete stock universe with fundamental metadata.
   - `instruments`: Active tradable stock universe filtered by Mcap & Price.
   - `market_data`: Daily OHLCV records for each instrument.
   - `indicators`: Technical indicators computed per stock per date.
   - `percentile`: Cross-sectional 0–100 percentile ranks.
   - `score`: Daily composite scores and penalty records.
   - `ranking`: Weekly average scores and ranks (1 = top stock).

2. **Personal Database (`personal.db`)**: Stores live account trading state:
   - `config`: Portfolio risk & sizing parameters.
   - `actions`: Pending/Approved/Rejected trading actions (BUY, SELL, SWAP).
   - `investment_holdings`: Active portfolio positions, cost basis, trailing stop loss.
   - `investment_summary`: Weekly portfolio valuation, invested capital, remaining cash.
   - `capital_events`: Cash infusions, withdrawals, and realized gain entries.
   - `backtest_runs`: Metadata records for past backtest simulations.

3. **Backtest Database (`backtest.db`)**: Isolated sandbox database bind.
   - Used by `WeeklyBacktester` to mirror live trading logic (`actions`, `investment_holdings`, `investment_summary`, `capital_events`) without touching `personal.db`.

---

### 3. Data Ingestion & Integration Adaptors (`src/adaptors/`)

- **`KiteAdaptor` (`kite_adaptor.py`)**:
  - Handles OAuth login via a local HTTP server listening on port 80/redirect_url, saving `access_token.txt`.
  - Fetches daily OHLCV historical data and tradable instruments list.
  - Features REST-based OHLC fetching (`fetch_ohlc`) for indices and holdings.
  - Implements background `KiteTicker` WebSocket for real-time price updates.
- **`BenchmarkAdaptor` (`benchmark_adaptor.py`)**:
  - Fetches Nifty 500 index (`NSE:NIFTY 500`, token 268041) daily close prices directly via `KiteConnect`.
  - Automatically chunks requests over 400 days.
  - Falls back to `yfinance` (`^CNX500`) if Kite is unavailable.
  - In-memory caching per `(start_date, end_date)` range.
- **`YFinanceAdaptor` (`yfinance_adaptor.py`)**:
  - Fetches fundamental metrics (`regularMarketPrice`, `marketCap`, `sharesOutstanding`, `floatShares`, `heldPercentInsiders`, `heldPercentInstitutions`, `industry`, `sector`).
  - Detects HTTP 429 rate-limiting responses (`RateLimitError`) for exponential back-off retries.

---

### 4. Multi-Factor Quantitative Scoring Engines (`src/config/strategies_config.py`, `src/services/factors_service.py`)

The platform supports two distinct quantitative strategies:

#### Strategy 1 (`strategy1` - Original Multi-Factor Momentum)
- **Trend (30%)**:
  - *Distance from 200 EMA* (40% sub-weight): Non-linear **Goldilocks curve** (0–10% distance = 70–85 score; 10–35% sweet spot = 85–100 score; >35% over-extended decay).
  - *EMA 50 Slope* (60% sub-weight): 5-day rate-of-change normalised to 0–100.
- **Momentum (25%)**:
  - *RSI 14* (20% sub-weight): Non-linear regime curve (<40 = 0 score; 50–70 sweet spot = 30–100 score; >85 overbought floor at 60).
  - *PPO (12, 26, 9)* (20% sub-weight): Normalised to 0–100.
  - *Skip-5 Pure Momentum* (60% sub-weight): Average of 3-month and 6-month log returns skipping the latest 5 trading days to avoid short-term mean-reversion noise.
- **Risk Efficiency (20%)**:
  - *Risk-Adjusted Return*: `ROC_20 / (ATR_14 / Close)` with ATR spike penalty (>2.0 ratio reduces bucket score by 50%).
- **Volume & Conviction (15%)**:
  - *RVOL* (70% sub-weight): Relative volume vs 20-day SMA, capped at 3x.
  - *Price-Volume Correlation* (30% sub-weight): 10-day Pearson correlation of returns vs volume.
- **Structure (10%)**:
  - *Bollinger Band %B* (50% sub-weight): Non-linear position within bands.
  - *Bandwidth Expansion* (50% sub-weight): 5-day rate of change of BB bandwidth.
- **Global Soft Penalties**:
  - Price < 200 EMA: score multiplied by **0.5**.
  - Price < 50 EMA: score multiplied by **0.7**.
  - Hard Exclusions: Penny stocks (< ₹50) and low turnover (< ₹0.5 Cr).

#### Strategy 2 (`strategy2` - Institutional Multi-Factor Framework)
Based on quantitative research on Indian Equities:
- **Trend (30%)**:
  - *EMA 50 Slope* (70% sub-weight): Primary trend direction.
  - *EMA 200 Distance* (30% sub-weight): Cross-sectional Z-score capped at ±2.0 to prevent double-penalising extended leaders.
- **Momentum (25%)**:
  - *Mansfield Relative Strength vs Nifty 500* (40% sub-weight): `RS = (Close / Nifty500) - 1`, `MRS = (RS / SMA_200(RS)) - 1`. Values > 0 indicate outperforming the broader benchmark.
  - *NSE Normalised Volatility-Adjusted Momentum* (30% sub-weight): `(LogRet_6M/σ_ann + LogRet_12M/σ_ann) / 2` with 5-day skip.
  - *PPO* (20% sub-weight) + *Pure 6M Momentum* (10% sub-weight).
- **Risk Efficiency (20%)**:
  - *Annualised Sortino Ratio* (70% sub-weight): Uses 6% risk-free rate (GoI T-bill proxy) and 252-day downside deviation.
  - *Local ATR Spike Filter* (30% sub-weight): Localised penalty instead of global multiplier.
- **Volume & Liquidity (15%)**:
  - *RVOL* (40% sub-weight).
  - *Scaled Turnover (Illiquidity Premium)* (30% sub-weight): `Daily_Turnover / (Close * Vol_SMA_20)`. Lower values represent illiquid momentum stocks with higher historical alpha.
  - *Log-Return Price-Volume Correlation* (30% sub-weight): 20-day Pearson correlation using stationary log returns.
- **Structure & Quality (10%)**:
  - *Quality Z-Score* (50% sub-weight): Fundamental quality proxy.
  - *Bandwidth Expansion* (30% sub-weight).
  - *RSI 14* (20% sub-weight): Demoted to an entry-timing filter.
- **ADX Global Regime Multiplier**:
  - Gated by 14-period ADX:
    - ADX < 20 (choppy market): Trend + Momentum contribution multiplied by **0.50**.
    - 20 ≤ ADX ≤ 30 (neutral market): Multiplied by **1.00**.
    - ADX > 30 (strong/exhaustion trend): Multiplied by **0.90**.
  - No global EMA soft penalties.

---

### 5. Full Data Processing Pipeline (`src/services/`)

1. **`InitService` (`init_service.py`)**:
   - Merges NSE and BSE CSV import files using ISIN as primary key.
   - Filters out mutual funds, asset management companies, and ETFs.
   - Queries `yfinance` in rate-limited batches (100 stocks/batch with sleep intervals) for company fundamentals.
   - Inserts raw universe into `master_stocks`.
   - Filters universe by Market Cap (≥ ₹500 Cr) and Price (≥ ₹75).
   - Syncs with Kite instruments API to create `instruments` table. Handles series change detection (`EQ` vs `BE`).

2. **`MarketDataService` (`marketdata_service.py`)**:
   - Incrementally fetches daily OHLCV from Kite Connect API.
   - **Corporate Action Detection**: Compares stored close price against fetched close price for the same date. If prices differ (due to stock split or bonus), triggers automatic full historical refill and cascades deletion across `market_data` and `indicators`.

3. **`IndicatorsService` (`indicators_service.py`)**:
   - Runs `pandas_ta` studies (`ema_strategy`, `momentum_strategy`, `derived_strategy`, `strategy2_adx_study`).
   - Computes derived indicators (price-volume correlation, %B, EMA slopes, ATR spike, risk-adjusted returns, Mansfield RS, Sortino, Scaled Turnover).
   - Features `patch_indicators()` for targeted column backfills on missing indicators without recalculating existing history.

4. **`PercentileService` (`percentile_service.py`)**:
   - Evaluates raw factor formulas via `FactorsService` / `FactorsServiceV2`.
   - Applies cross-sectional `percentile_rank()` across all stocks on each date to compute 0–100 percentile scores for each factor.
   - Tagged by `strategy_id` in the `percentile` table.

5. **`ScoreService` (`score_service.py`)**:
   - Applies weighted top-level strategy parameters to calculate `initial_composite_score`.
   - Applies strategy-specific penalties (Strategy 1 soft EMA multipliers vs Strategy 2 ADX regime multiplier + hard exclusions).
   - Writes final `composite_score` to the `score` table tagged by `strategy_id`.

6. **`RankingService` (`ranking_service.py`)**:
   - Aggregates daily composite scores for each Mon–Fri calendar week.
   - Computes weekly average composite score per stock.
   - Ranks all stocks descending (Rank 1 = top stock) and inserts into the `ranking` table tagged by `strategy_id`.

---

### 6. Trading Decision & Portfolio Execution System (`src/services/`)

```mermaid
sequenceDiagram
    autonumber
    participant UI as API / Operator
    participant AG as ActionGenerator
    participant TE as TradingEngine
    participant AL as ActionLifecycle
    participant AP as ActionProcessor
    participant IS as InvestmentService
    participant DB as SQLite (personal.db)

    UI->>AG: generate_actions(action_date)
    AG->>TE: generate_decisions(holdings, top_n_candidates)
    Note over TE: Phase 1: SELL check (SL hit or score < 40)<br/>Phase 2: Candidate loop (BUY / PYRAMID / SWAP)
    TE-->>AG: List[TradingDecision]
    AG->>AG: Execute Sells -> Pyramids -> Buys with ATR Sizing
    AG->>DB: Bulk insert pending actions to actions table
    UI->>AL: approve_all_actions(action_date)
    Note over AL: Phase 1: Approve Sells at Monday Open (Release Cash)<br/>Phase 2: Re-size Buys at Monday Open (Gated by Cash)
    AL->>DB: Update actions table (status=Approved, execution_price)
    UI->>AP: process_actions(action_date)
    Note over AP: Realize PnL -> Insert Capital Event -> Update Holdings & Summary
    AP->>IS: get_summary(week_holdings, sold, bought)
    IS-->>AP: summary_dict (First-Principles Accounting)
    AP->>DB: Upsert investment_holdings & investment_summary
```

- **`TradingEngine` (`trading_service.py`)**:
  - Pure decision logic engine (`generate_decisions`).
  - **Phase 1 (SELL)**: Flag positions where `current_sl > current_price` or `score < 40.0` (exit threshold).
  - **Phase 2 (Candidate Loop)**: Iterates top-ranked candidates by score descending:
    - *PYRAMID_ADD*: If already held, pyramiding enabled, `stop_loss >= entry_price`, and `EMA_50 > avg_price`.
    - *BUY*: If not held and open position vacancy exists (< `max_positions` 15).
    - *SWAP*: If not held, no vacancy, and candidate score > `1.25 * weakest_holding_score`.
- **`ActionGenerator` (`action_generator.py`)**:
  - Builds typed `BuyActionResult` and `SellActionResult` objects.
  - Sizing via `calculate_position_size()` (`sizing_utils.py`): Risk-parity sizing (`Risk% * Total_Capital / (ATR * SL_Multiplier)`), capped by available cash (`remaining_capital`), capped by max position concentration (25%), and filtered by minimum position size (5%).
- **`ActionLifecycle` (`action_lifecycle.py`)**:
  - Controls status transitions (`Pending` → `Approved` | `Rejected`).
  - **Two-Phase Monday Approval**:
    - *Phase 1 (Sells)*: Approved at Monday open price; proceeds added to cash and sizing base.
    - *Phase 2 (Buys)*: Re-sized at Monday open execution price; approved if cash permits, remaining stay Pending.
- **`ActionProcessor` (`action_processor.py`)**:
  - Executes approved actions into database records:
    - *Sells*: Calculates realized PnL, inserts `capital_events` row (`realized_gain`), deletes holding.
    - *Pyramids*: Computes weighted average cost basis (`avg_price`), updates units, maintains existing stop loss.
    - *Buys*: Inserts new holding with initial ATR stop loss.
    - *Holds*: Updates trailing ATR stop loss (`calculate_effective_stop`) which trails upward only.

---

### 7. Portfolio Accounting & Journal (`src/services/investment_service.py`, `src/utils/`)

- **First-Principles Cash Accounting**:
  - `total_capital` = SUM of capital events (infusions/withdrawals + realized gains).
  - `cost_basis` = SUM of `avg_price * units` for active open holdings.
  - `remaining_capital` = `total_capital - cost_basis`.
  - Prevents cash drift across weekly cycles.
- **XIRR Engine (`metrics.py`)**:
  - Computes Extended Internal Rate of Return using exact cashflow dates (infusions as negative cashflows, current portfolio valuation as terminal positive cashflow) via `scipy.optimize.newton` with `brentq` fallback.
- **FIFO Trade Journal (`fifo_matcher.py`)**:
  - Matches approved sell actions to earlier buy lots in First-In-First-Out order to determine exact trade PnL, return %, and holding period in days.

---

### 8. Backtesting Simulation Framework (`src/services/backtesting_service.py`, `backtest_report_builder.py`)

- **`WeeklyBacktester`**:
  - Runs historical backtests over a specified date range using an isolated `backtest.db` SQLite session.
  - Reuses exact live trading services (`ActionGenerator`, `ActionLifecycle`, `ActionProcessor`).
  - **Daily Stop-Loss Check (`check_daily_sl`)**:
    - *Phase 1 (Hard SL)*: Checks daily low against hard stop floor (`Entry_SL * (1 - 0.03)`). Executes same-day intraday sell.
    - *Phase 2 (Close SL)*: Checks daily close against trailing stop. Generates sell executed at next day's open.
  - **Mid-Week Vacancy Fills (`mid_week_buy`)**: Fills pending buys mid-week when vacancies open up after stop-loss exits.
  - **End-of-Backtest Force Close**: Force-closes all remaining open positions on the final backtest date at the latest close price to realize final PnL and tax metrics.
- **`BacktestReportBuilder`**:
  - Formats detailed text report containing Configuration, Performance Metrics (CAGR, Sharpe, Sortino, Calmar, Max Drawdown, XIRR), Year-on-Year (YoY) breakdown, Trade Statistics (Win Rate, Profit Factor, Expectancy), Open Positions, and Full Trade Log.
  - Saves run artifacts to `backtest_history/{timestamp}_{run_id}/` (summary.json, equity_curve.json, trades.json, report.txt).

---

## Complete Database Schema Summary

| Table | Bind | Primary Key | Description |
| :--- | :--- | :--- | :--- |
| `master_stocks` | Default | `isin` | Master universe of Indian equities with fundamental metadata |
| `instruments` | Default | `instrument_token` | Filtered active trading universe synced with Zerodha Kite |
| `market_data` | Default | `(instrument_token, date)` | Daily OHLCV price history |
| `indicators` | Default | `(tradingsymbol, date)` | Computed technical indicators (EMA, RSI, PPO, ATR, Mansfield RS, Sortino, ADX) |
| `percentile` | Default | `(tradingsymbol, percentile_date, strategy_id)` | Cross-sectional 0–100 percentile ranks per factor |
| `score` | Default | `(tradingsymbol, score_date, strategy_id)` | Daily composite scores and penalty/regime reason notes |
| `ranking` | Default | `(tradingsymbol, ranking_date, strategy_id)` | Weekly average scores and ranks (1 = top rank) |
| `config` | Personal | `id` | Risk & position sizing configuration parameters |
| `actions` | Personal/Backtest | `action_id` | Trading actions generated (BUY/SELL/SWAP, status: Pending/Approved/Rejected) |
| `investment_holdings` | Personal/Backtest | `(symbol, date)` | Active portfolio positions, cost basis, trailing stop loss |
| `investment_summary` | Personal/Backtest | `date` | Weekly portfolio valuation, capital risk, portfolio risk, remaining cash |
| `capital_events` | Personal/Backtest | `id` | Cash infusions, withdrawals, and realized gain records |
| `backtest_runs` | Personal | `id` | Metadata log for past backtest simulations |

---

## API Endpoints Reference

### System & App Orchestration (`/api/v1/app`, `/api/v1/init`)
- `POST /api/v1/init/app`: Execute Day 0 universe initialization & yfinance fetch.
- `GET /api/v1/app/logs/stream`: SSE real-time log stream for pipeline execution.
- `POST /api/v1/app/run-pipeline`: Run full pipeline with selectable step toggles (`init`, `marketdata`, `indicators`, `percentile`, `score`, `ranking`).
- `POST /api/v1/app/recalculate`: Recalculate downstream tables from `start_date`.
- `DELETE /api/v1/app/cleanup`: Delete records after `start_date` across selected tables.

### Data Pipeline (`/api/v1/marketdata`, `/api/v1/indicators`, `/api/v1/percentile`, `/api/v1/score`, `/api/v1/ranking`)
- `POST /api/v1/marketdata/update`: Update market data OHLCV for all instruments.
- `POST /api/v1/indicators/calculate`: Calculate technical indicators.
- `POST /api/v1/indicators/patch`: Backfill specific missing indicator columns.
- `POST /api/v1/percentile/calculate`: Compute cross-sectional factor percentiles.
- `POST /api/v1/score/calculate`: Calculate composite scores.
- `POST /api/v1/ranking/calculate`: Calculate weekly rankings.

### Trading & Portfolio (`/api/v1/actions`, `/api/v1/investment`)
- `POST /api/v1/actions/generate`: Generate weekly trading actions.
- `GET /api/v1/actions/`: Get actions for a specific date.
- `POST /api/v1/actions/approve`: Approve pending actions (Phase 1 sells, Phase 2 buys).
- `POST /api/v1/actions/process`: Process approved actions into holdings & summary.
- `POST /api/v1/actions/reject-all`: Reject remaining pending actions.
- `GET /api/v1/investment/summary`: Get current portfolio summary (portfolio value, gain %, XIRR, risk).
- `GET /api/v1/investment/holdings`: Get active portfolio holdings.
- `GET /api/v1/investment/trades`: Get FIFO trade journal.
- `POST /api/v1/investment/capital`: Record cash infusion/withdrawal.

### Backtesting (`/api/v1/backtest`)
- `POST /api/v1/backtest/run`: Run strategy simulation across date range.
- `GET /api/v1/backtest/history`: List saved backtest runs.
- `GET /api/v1/backtest/history/<id>`: Get full backtest run data & report.
- `DELETE /api/v1/backtest/history/<id>`: Delete backtest run from history.

### Index Live Ticker (`/api/v1/index`)
- `POST /api/v1/index/start`: Start background REST polling thread for index prices (Nifty 50, Nifty 100, Nifty Bank, Sensex).
- `GET /api/v1/index/prices`: Get latest cached index prices.
- `POST /api/v1/index/stop`: Stop index ticker thread.

---

## Questionnaire / Clarification Notes for User

Based on our complete source code inspection without assumptions:

1. **Current Codebase State**: The codebase is fully implemented with dual-strategy quantitative models (`strategy1` and `strategy2`), complete REST API endpoints, full portfolio accounting with XIRR, and backtesting simulation capabilities.
2. **Execution Flow**: The code is clean, strictly modularized (Adaptors → Models → Repositories → Services → Routes), and uses first-principles mathematical formulas throughout.
3. **No Assumptions Made**: All facts in this document were verified directly from reading every single source code file.

---
*Generated by Antigravity AI Codebase Analysis*
