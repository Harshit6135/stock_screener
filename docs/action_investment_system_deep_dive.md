# Actions, Investments & Full System Deep Dive

> **Companion to:** `ranking_system_deep_dive.md`  
> **Scope:** Everything the repo does *after* rankings are generated — the three-step action lifecycle, portfolio management, backtesting engine, all remaining API routes, and shared utility layers.

Together, these two documents cover **100% of the codebase** with no gaps.

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Configuration Layer](#2-configuration-layer)
3. [The Three-Step Action Lifecycle](#3-the-three-step-action-lifecycle)
   - 3.1 [Step 1 — Generate (`ActionGenerator`)](#31-step-1--generate-actiongenerator)
   - 3.2 [Step 2 — Approve (`ActionLifecycle`)](#32-step-2--approve-actionlifecycle)
   - 3.3 [Step 3 — Process (`ActionProcessor`)](#33-step-3--process-actionprocessor)
4. [Portfolio / Investment Layer](#4-portfolio--investment-layer)
   - 4.1 [Holdings & Stop-Loss Ratchet](#41-holdings--stop-loss-ratchet)
   - 4.2 [Portfolio Summary Calculation](#42-portfolio-summary-calculation)
   - 4.3 [Capital Events & XIRR](#43-capital-events--xirr)
   - 4.4 [Trade Journal (FIFO Matching)](#44-trade-journal-fifo-matching)
   - 4.5 [Live Ticker (WebSocket Streaming)](#45-live-ticker-websocket-streaming)
5. [Manual Trade Service](#5-manual-trade-service)
6. [Backtesting Engine](#6-backtesting-engine)
   - 6.1 [Weekly Simulation Loop](#61-weekly-simulation-loop)
   - 6.2 [Daily Stop-Loss Loop](#62-daily-stop-loss-loop)
   - 6.3 [Risk Monitor & Metrics](#63-risk-monitor--metrics)
   - 6.4 [Report Builder & History](#64-report-builder--history)
7. [Transaction Costs & Tax Utilities](#7-transaction-costs--tax-utilities)
8. [Position Sizing Utility](#8-position-sizing-utility)
9. [App Orchestration (Pipeline Runner)](#9-app-orchestration-pipeline-runner)
10. [API Route Reference](#10-api-route-reference)
11. [Database Schema — Personal DB](#11-database-schema--personal-db)
12. [Full System Interaction Diagram](#12-full-system-interaction-diagram)

---

## 1. System Architecture Overview

The system is split into two logical databases and a clear service hierarchy:

```
┌─────────────────────────────────────┐    ┌──────────────────────────────────┐
│         MARKET DB (read-only here)  │    │        PERSONAL DB (R/W)         │
│                                     │    │                                  │
│  market_data   indicators           │    │  config          actions         │
│  percentile    score                │    │  investment_holdings             │
│  ranking       instruments          │    │  investment_summary              │
│  master                             │    │  capital_events                  │
│                                     │    │  backtest_runs                   │
└─────────────────────────────────────┘    └──────────────────────────────────┘
         Read by ActionGenerator                   Written by all services below
```

### Service Responsibility Boundaries

| Service | Reads From | Writes To |
|---|---|---|
| `ActionGenerator` | ranking, market_data, indicators, investments | actions |
| `ActionLifecycle` | actions, investments, market_data | actions (status updates only) |
| `ActionProcessor` | actions (approved), investments | investment_holdings, investment_summary, capital_events |
| `InvestmentService` | investments, actions, indicators, ranking | investment_holdings, investment_summary |
| `ManualTradeService` | market_data, investments | actions |
| `WeeklyBacktester` | ranking, market_data, indicators | backtest DB (isolated session) |

---

## 2. Configuration Layer

### `ConfigModel` — Runtime Trading Parameters

**File:** [`src/models/config_model.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/models/config_model.py)  
**API:** `GET/PUT/POST /api/v1/config/<config_name>`

All live trading and backtest parameters are stored in the **`config` table**, not hard-coded. This enables parameter sweeps via backtesting without code changes.

| Parameter | Default | Description |
|---|---|---|
| `config_name` | `"momentum_config"` | Strategy identifier (FK for all other tables) |
| `initial_capital` | ₹1,00,000 | Starting capital for backtests; used for sizing in live trading |
| `risk_threshold` | 1.0% | % of total capital to risk per trade (ATR sizing input) |
| `max_positions` | 15 | Maximum simultaneous positions |
| `min_position_percent` | 5% | Minimum position as % of total capital — rejects too-small buys |
| `exit_threshold` | 40.0 | Composite score below which a holding is sold |
| `buffer_percent` | 25% | SWAP buffer: candidate must beat weakest by `1 + buffer_percent` |
| `sl_multiplier` | 2.0 | ATR multiplier for stop-loss distance |
| `hard_sl_percent` | 3% | Hard SL is `current_sl × (1 - 0.03)` — intraday gap protection |
| `max_concentration_pct` | 25% | Maximum capital in a single stock |
| `atr_fallback_percent` | 6% | Fallback risk if ATR is zero (use 6% of price as stop-distance) |

### `TaxConfig` — Indian Capital Gains Parameters

**File:** [`src/config/tax_config.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/config/tax_config.py)

| Parameter | Value | Description |
|---|---|---|
| `stcg_rate` | 20% | STCG tax (holding < 365 days) |
| `ltcg_rate` | 12.5% | LTCG tax (holding >= 365 days) |
| `ltcg_exemption` | ₹1,25,000 | Annual LTCG exemption per FY |
| `ltcg_holding_days` | 365 | Days to qualify for LTCG |
| `tax_hold_window_start` | 300 | Days at which LTCG-bias kicks in |
| `tax_hold_min_score` | 50.0 | Minimum composite score to hold for LTCG |

### `TransactionCostConfig` — Indian Market Costs

**File:** [`src/config/cost_config.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/config/cost_config.py)

| Cost | Rate | Side |
|---|---|---|
| STT | 0.1% | Buy + Sell |
| Exchange | 0.00345% | Buy + Sell |
| SEBI | ₹10/crore | Buy + Sell |
| Stamp Duty | 0.015% | Buy only |
| GST | 18% on brokerage+exchange+SEBI | Buy + Sell |
| IPF | ₹10/crore | Buy + Sell |
| DP Charges | ₹13/transaction | Sell only |

---

## 3. The Three-Step Action Lifecycle

Every trade — whether generated automatically on Monday or entered manually — passes through the same three stages:

```
Generate → Approve → Process
   │            │         │
   ▼            ▼         ▼
actions      actions  investment_holdings
table        (status  investment_summary
(Pending)   update)   capital_events
```

### 3.1 Step 1 — Generate (`ActionGenerator`)

**File:** [`src/services/action_generator.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/action_generator.py)  
**API trigger:** `POST /api/v1/actions/generate`

#### `generate_actions(action_date, enable_pyramiding, check_daily_sl, mid_week_buy)`

```
action_date = Monday (or any business day)
data_date   = get_prev_friday(action_date)   ← the signal date

1. Load top-N ranked stocks for data_date
   → ranking_repo.get_top_n_by_date(config.max_positions, data_date)

2. Load portfolio context
   ├── current_holdings  (InvestmentRepository.get_holdings)
   ├── total_capital     = get_total_capital(include_realized=True)
   └── remaining_capital = summary.remaining_capital

3. Load market context for data_date
   ├── Friday closes for all top-N + holdings
   ├── EMA-50 values (for pyramid eligibility)
   └── Composite scores from ranking table

4. TradingEngine.generate_decisions()  [pure, stateless]

   PHASE 1 — SELL decisions (exit before entries):
   For each holding:
   ├── If current_price < current_sl     → SELL (stop-loss hit)
   └── If composite_score < exit_threshold (40.0)  → SELL (degraded)

   PHASE 2 — Candidate loop (sorted by composite_score DESC):
   For each candidate in top-N:
   ├── Case A: Already held + pyramiding enabled:
   │   └── If current_sl >= entry_price (position profitable)
   │       AND EMA-50 >= avg_price (trend intact)
   │       → PYRAMID_ADD
   ├── Case B: Not held + open slots:
   │   └── BUY
   └── Case C: Not held + no slots + score > weakest_holding × swap_buffer:
       └── SWAP (sell weakest, buy this)
           [swap_buffer = 1 + config.buffer_percent, default 1.25]

5. Execute decisions:
   Phase 1 — SELLs: create sell_action at Friday close
   Phase 2 — PYRAMID: sized at PyramidConfig.pyramid_fraction % of total_capital
   Phase 3 — BUYS: create buy_action (ATR-sized), backfill slots if capital allows

6. Bulk insert all actions into actions table with status='Pending'
   (De-duplicated: one action per symbol per date)
```

#### `check_daily_stoploss(day, mid_week_buy)` — Mid-Week SL Check

Runs on non-Monday days (Tue–Thu):
```
For each holding:
  ├── If close < current_sl → create Pending SELL dated tomorrow's open
  └── If mid_week_buy AND sell created → advance next pending BUY to fill vacancy

Stale buy guard: skip any pending BUY where price > 5% above signal close
```

#### `buy_action()` — ATR Position Sizing (Shared with Manual Trades)

```python
risk_per_unit  = ATR × sl_multiplier
units          = calculate_position_size(atr, price, total_capital, remaining_capital, config)
stop_loss      = price - risk_per_unit
hard_sl_price  = stop_loss × (1 - hard_sl_percent)  [e.g. 3% below soft SL]
capital        = units × price
```

### 3.2 Step 2 — Approve (`ActionLifecycle`)

**File:** [`src/services/action_lifecycle.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/action_lifecycle.py)  
**API trigger:** `POST /api/v1/actions/approve?date=YYYY-MM-DD`

> **Responsibility boundary:** Reads actions + holdings + market data. Writes **only** to the `actions` table (status transitions). No holdings are mutated here.

#### `approve_all_actions(action_date)`

```
Initial capital setup:
  remaining_capital = summary.remaining_capital (or get_total_capital if no summary)
  sizing_base       = get_total_capital(include_realized=True)

PHASE 1 — Approve SELLs (always approved first, releases capital):
  For each pending SELL action:
  ├── Fetch holding to get entry_price
  ├── execution_price = action.execution_price OR Monday's open price
  ├── Calculate costs:   calculate_transaction_costs(sell_value, "sell")
  ├── Calculate tax:     calculate_capital_gains_tax(entry_price, exec_price, ...)
  ├── Update action: status="Approved", execution_price, sell_cost, tax
  ├── remaining_capital += sell_proceeds
  └── sizing_base += realized_PnL

PHASE 2 — Approve BUYs (capital-constrained, re-sized at actual price):
  For each pending BUY action:
  ├── execution_price = action.execution_price OR Monday's open price
  ├── Re-size using calculate_position_size(atr, exec_price, sizing_base, remaining_capital, config)
  ├── If units == 0 → stay Pending (capital-constrained, not rejected)
  ├── Calculate costs:   calculate_transaction_costs(capital_needed, "buy")
  ├── Update action: status="Approved", units (re-sized), capital, execution_price, buy_cost
  └── remaining_capital -= capital_needed

Returns: count of approved actions (sells + buys)
```

> **Key design:** Sells happen first so their proceeds fund new buys within the same Monday. This avoids needing to hold excess cash for swap transitions.

#### `reject_pending_actions()`

Marks all `Pending` actions as `Rejected`. Called:
- At start of each new week (to clear unfilled buys from last week)
- Explicitly via `POST /api/v1/actions/reject-all`

### 3.3 Step 3 — Process (`ActionProcessor`)

**File:** [`src/services/action_processor.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/action_processor.py)  
**API trigger:** `POST /api/v1/actions/process?date=YYYY-MM-DD`

> **Responsibility boundary:** Reads approved actions. Writes **only** to `investment_holdings`, `investment_summary`, and `capital_events`.

#### `process_actions(action_date, midweek=False)`

```
Safety check: holdings_date must be BEFORE action_date (prevent double-processing)

Build maps:
  sell_symbols = {symbol: action for approved SELLs}
  buy_symbols  = {symbol: action for approved BUYs}
  holdings_map = {symbol: holding for current holdings}
  held_symbols = set of currently held symbols

PHASE 1 — Sell Processing:
  For each symbol in sell_symbols:
  ├── Intraday case: symbol in buy_symbols but NOT in holdings_map
  │   → treat the buy action as a phantom holding (sell from fresh buy)
  ├── Normal case: get holding from holdings_map
  ├── Calculate PnL = (exec_price - avg_price) × units
  ├── Insert capital_event: type="realized_gain", amount=PnL
  ├── delete_holding(symbol, action_date)
  └── Add to sold_symbol_set

PHASE 2 — Buy Processing:
  data_date = get_prev_friday(action_date)

  For each symbol in buy_symbols (not in sell_symbols):
  ├── Pyramid Add (action.reason == "pyramid_add"):
  │   ├── Fetch existing holding
  │   ├── New avg_price = (old_value + new_value) / total_units
  │   ├── Keep existing SL (stop-loss NOT reset on pyramid)
  │   ├── Look up latest composite_score from ranking table
  │   └── Create merged HoldingResult (entry_date preserved)
  │
  └── Normal Buy:
      ├── Compute initial_sl = exec_price - (ATR × sl_multiplier)
      ├── Look up composite_score from ranking table
      └── Create new HoldingResult (entry_date = action_date)

PHASE 3 — Update Unchanged Holdings:
  For each held_symbol not sold or pyramid-added:
  ├── Fetch Friday close + ATR for this symbol
  ├── Compute trailing stop: calculate_effective_stop(current_price, ATR, sl_mult, prev_SL)
  │   └── New SL = max(prev_SL, current_price - ATR × sl_mult)  [ratchet: SL never goes down]
  └── Update score from Friday's ranking

Final:
  summary = InvestmentService.get_summary(week_holdings, sold, bought, action_date)
  investment_repo.upsert_holdings(week_holdings_dicts, action_date)
  investment_repo.upsert_summary(summary)
```

---

## 4. Portfolio / Investment Layer

### 4.1 Holdings & Stop-Loss Ratchet

**Model:** `InvestmentsHoldingsModel` (table: `investment_holdings`)

| Column | Notes |
|---|---|
| `symbol` | Primary key (with `date`) |
| `date` | Date this snapshot was written (Monday action date) |
| `entry_date` | Date of first purchase (preserved across pyramids) |
| `entry_price` | Price at first purchase |
| `avg_price` | Weighted average cost (updated on pyramid adds) |
| `units` | Total units held |
| `atr` | ATR at last weekly update |
| `score` | Latest composite_score from ranking |
| `entry_sl` | Stop-loss at time of first purchase |
| `current_price` | Close price on last update date |
| `current_sl` | Current trailing stop-loss (monotonically increasing) |

#### Stop-Loss Ratchet (`calculate_effective_stop`)

```python
# From utils/
new_stop = current_price - (current_atr × stop_multiplier)
final_stop = max(previous_stop, new_stop)  # SL never moves DOWN
```

This ensures winning trades automatically trail higher, protecting profits without manual intervention.

#### Trailing SL Update Cadence

- **Weekly (Monday):** Always updated from latest Friday indicators
- **Mid-week:** Only if `midweek=False` (default) — mid-week process runs carry SL forward unchanged

### 4.2 Portfolio Summary Calculation

**Service:** `InvestmentService.get_summary()`  
**Model:** `InvestmentsSummaryModel` (table: `investment_summary`)  
**API:** `GET /api/v1/investment/summary`

The summary is computed **from first principles** every time, not from cached deltas:

```
total_cap_with_realized = Σ capital_events.amount (all types, up to action_date)
cost_basis              = Σ (avg_price × units) for all current holdings
remaining_capital       = total_cap_with_realized - cost_basis

portfolio_value         = Σ (current_price × units) + remaining_capital
gain                    = portfolio_value - total_initial_capital
gain_percentage         = gain / total_initial_capital × 100

capital_risk            = Σ (units × (entry_price - current_sl))   [downside risk from entry]
portfolio_risk          = Σ (units × (current_price - current_sl)) [downside from current]
```

**Live recalculation** (`GET /api/v1/investment/summary`):
- Fetches stored summary from DB
- Re-adds live `XIRR`, `portfolio_risk`, `capital_risk`, `unrealized_gain`, `realized_gain` on top

**Historical summaries** (`GET /api/v1/investment/summary/history`):
- Returns all weekly snapshots — used for equity curve and drawdown chart

### 4.3 Capital Events & XIRR

**Model:** `CapitalEventModel` (table: `capital_events`)  
**API:** `GET/POST /api/v1/investment/capital-events`

| `event_type` | When | Amount sign |
|---|---|---|
| `initial` | First capital injection | Positive |
| `infusion` | Additional capital added | Positive |
| `withdrawal` | Capital taken out | Negative |
| `realized_gain` | Auto-inserted on each sell | Positive (gain) or negative (loss) |

**Total Capital Calculation:**

```python
total_capital = Σ capital_events.amount
               where event_type IN ('initial', 'infusion', 'withdrawal')
               and date <= as_of_date
```

**XIRR Calculation:**
```python
cashflows = [(-amount, event_date) for each capital event]  # negative = outflow
cashflows.append((current_portfolio_value, today))           # positive = terminal value
xirr = calculate_xirr(cashflows) × 100  # returns % annualized return
```

### 4.4 Trade Journal (FIFO Matching)

**API:** `GET /api/v1/investment/trade-journal`  
**Utility:** `FIFOTradeTracker.from_actions(all_actions)`

Matches every sell to the earliest unmatched buy (First-In, First-Out) to compute:

```
matched_trades = FIFO_match(all_approved_actions)

For each matched trade:
  ├── entry_date, exit_date
  ├── symbol, units
  ├── entry_price, exit_price
  ├── pnl = (exit_price - entry_price) × units
  ├── return_pct = pnl / (entry_price × units) × 100
  ├── days_held = (exit_date - entry_date).days
  └── reason (stoploss / score_exit / swap / backtest_end_close / etc.)
```

> This same FIFO tracker is used identically in backtesting — ensuring trade journal and backtest trade metrics are computed by exactly the same logic.

### 4.5 Live Ticker (WebSocket Streaming)

**API:** `POST /api/v1/investment/start-ticker` / `GET /api/v1/investment/live-prices` / `POST /api/v1/investment/stop-ticker`

The live ticker uses the **Zerodha Kite WebSocket API** to stream real-time prices for current holdings:

```
POST /start-ticker:
  1. Load current holdings → get symbols
  2. Resolve symbol → instrument_token via InstrumentsModel
     ├── NSE EQ:   plain symbol (e.g. RELIANCE)
     ├── NSE BE:   plain symbol (BE series stripped internally)
     └── NSE other: SYMBOL-SERIES
  3. Pre-fetch prev_close via kite.ohlc() (REST call)
  4. Populate live_prices cache with prev_close + last_price + % change
  5. Start kite.start_ticker(token_symbol_map)  ← WebSocket connection

GET /live-prices:
  → Returns {prices: {symbol: {last_price, prev_close, change%}}, is_streaming: bool}

POST /stop-ticker:
  → kite.stop_ticker()
```

The `KiteAdaptor` singleton is reused across requests to maintain a single WebSocket connection.

---

## 5. Manual Trade Service

**File:** [`src/services/manual_trade_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/manual_trade_service.py)  
**API:** `POST /api/v1/investment/manual/buy` and `POST /api/v1/investment/manual/sell`

Allows creating trades outside the weekly automated cycle. Manual actions **bypass the generate phase** but still require Approve + Process.

### Manual Buy

```
POST /api/v1/investment/manual/buy
Body: [{symbol, date, units, price, reason}]

For each stock:
  1. Look up market data for previous business day (for ATR)
  2. Check capital: if units × price > remaining_capital → skip (over_capital)
  3. Delegate to ActionGenerator.buy_action() for ATR sizing
  4. Set execution_price = provided price (overrides Friday close)
  5. Bulk insert with status="Pending"

→ Still needs Approve + Process to hit holdings
```

### Manual Sell

```
POST /api/v1/investment/manual/sell
Body: {symbol, date, units, price, reason}

For each stock:
  1. Validate symbol is in current holdings (skip if not)
  2. Fetch prev_close from previous business day market data
  3. Delegate to ActionGenerator.sell_action()
  4. Set execution_price = provided price
  5. Bulk insert with status="Pending"
```

---

## 6. Backtesting Engine

**File:** [`src/services/backtesting_service.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/services/backtesting_service.py)  
**API:** `POST /api/v1/backtest/run`

The backtest **reuses the exact same** `ActionGenerator`, `ActionLifecycle`, and `ActionProcessor` classes as live trading. The only difference is an **isolated SQLAlchemy session** writing to a separate `backtest.db` (not the live personal DB).

### 6.1 Weekly Simulation Loop

```
BacktestingService.run_backtest(start_date, end_date, config_name, ...)
  │
  ├── Initialize backtest DB (fresh, isolated session)
  ├── Seed initial capital event (initial_capital on start_date)
  │
  └── WeeklyBacktester.run():

      For each Monday in [start_date, end_date]:
        │
        ├── [0] Reject stale pending actions from last week
        │
        ├── [1] ActionGenerator.generate_actions(monday)
        │       Uses Friday rankings to decide BUY/SELL/SWAP
        │       (skip_pending_check=True for backtest)
        │
        ├── [2] ActionLifecycle.approve_all_actions(monday)
        │       Re-sizes buys at Monday open price
        │       Computes transaction costs + per-trade tax estimate
        │
        ├── [3] ActionProcessor.process_actions(monday)
        │       Updates backtest holdings + summary
        │
        ├── [4] Daily SL check (if check_daily_sl=True):
        │       _process_daily_stoploss(monday, friday)
        │
        ├── [5] BacktestRiskMonitor.update(portfolio_value, week_date)
        │
        └── [6] Record BacktestResult snapshot:
                {week_date, portfolio_value, total_return, max_drawdown,
                 actions, top_10_stocks, holdings}

      After all weeks:
        ├── _close_open_positions() — force-sell all at last close price
        ├── _build_trades_from_db() — FIFO-match all actions for trade metrics
        ├── BacktestReportBuilder.build() — generate text + JSON report
        └── BacktestHistoryRepository.save() — persist run to history
```

### 6.2 Daily Stop-Loss Loop

```
_process_daily_stoploss(monday, friday):

  pending_close_sl_symbols = set()

  For each business day in [monday, friday]:

    ── Pre-step: Set execution_price on yesterday's pending close-SL sells ──
    For each pending sell in pending_close_sl_symbols:
      → execution_price = today's open price

    ── Phase 1: Hard SL (intraday, same-day execution) ─────────────────────
    For each holding:
      ├── Skip if already has a pending close-SL from yesterday
      ├── Fetch today's OHLCV
      ├── hard_sl_price = current_sl × (1 - hard_sl_percent)
      └── If daily_low <= hard_sl_price:
          → execution_price = min(daily_low, hard_sl_price)  [worst-case fill]
          → Insert Pending SELL dated today

    ActionLifecycle.approve_all_actions(day)
    ActionProcessor.process_actions(day, midweek=(day != monday))

    ── Phase 2: Close-based SL (end-of-day, next-day execution) ─────────────
    If day < friday:
      close_sells = ActionGenerator.check_daily_stoploss(day, mid_week_buy)
      pending_close_sl_symbols = {s["symbol"] for s in close_sells}
      [These will be processed at tomorrow's open]
```

**Two SL types explained:**

| Type | Trigger | Execution |
|---|---|---|
| **Hard SL** | `daily_low <= current_sl × 0.97` | Same-day at worst of (low, hard_SL) |
| **Close-based SL** | `close_price < current_sl` | Next business day's open |

### 6.3 Risk Monitor & Metrics

`BacktestRiskMonitor` tracks the following in memory throughout the simulation:

```python
portfolio_values = [initial_capital, ...]   # snapshot after each week
portfolio_dates  = [start_date, ...]
peak_value       = max(portfolio_values)
max_drawdown     = max((peak - current) / peak × 100 for each week)
trades           = [FIFO-matched trade dicts]
```

`get_summary()` delegates to `calculate_all_metrics()` which produces:

| Metric | How Computed |
|---|---|
| **Total Return %** | `(final - initial) / initial × 100` |
| **CAGR** | `(final/initial)^(1/years) - 1` |
| **Max Drawdown %** | Rolling peak-to-trough |
| **Sharpe Ratio** | `(annualized return) / (annualized vol of weekly returns)` |
| **Win Rate** | Trades with PnL > 0 / total trades |
| **Avg Win / Avg Loss** | Mean PnL of winning / losing trades |
| **Profit Factor** | Total wins / Total losses |
| **Net Post-Tax Return** | Gross return − transaction costs − FY-bucketed capital gains tax |
| **STCG / LTCG Tax** | FY-bucketed netting (losses offset gains within same FY) |
| **Year-on-Year Returns** | `% change Jan 1 → Dec 31` for each calendar year |

### 6.4 Report Builder & History

**File:** `src/services/backtest_report_builder.py`

Generates a human-readable text report (`backtest_report_<timestamp>.txt`) containing:
- Configuration used
- Summary metrics table
- Year-on-year returns
- Open positions snapshot (unrealized at end date)
- Transaction cost breakdown
- STCG / LTCG tax breakdown

**Backtest History:**  
`BacktestHistoryRepository.save()` persists the run to `backtest_runs` table (metadata) and saves heavy data (equity curve, trades, report text) as JSON files in a `data_dir` on disk.

**API:** `GET /api/v1/backtest/history` (list) / `GET /api/v1/backtest/history/<id>` (detail) / `DELETE /api/v1/backtest/history/<id>`

---

## 7. Transaction Costs & Tax Utilities

### Transaction Costs

**File:** [`src/utils/transaction_costs_utils.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/utils/transaction_costs_utils.py)

```python
calculate_transaction_costs(trade_value, side) → dict
```

Returns:
```
{
  "brokerage": 0,          # Zero brokerage (Zerodha flat fee model not yet wired)
  "stt":       0.1% × value,
  "gst":       18% × (brokerage + exchange + sebi),
  "stamp":     0.015% × value (buy only),
  "dp":        ₹13 (sell only),
  "total":     sum of all
}
```

### Tax Utilities

**File:** [`src/utils/tax_utils.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/utils/tax_utils.py)

| Function | Purpose |
|---|---|
| `calculate_capital_gains_tax()` | Per-trade upper-bound estimate (STCG/LTCG) |
| `compute_trade_costs_and_taxes()` | FY-bucketed aggregate (losses offset gains within FY) |
| `should_hold_for_ltcg()` | Advisory: hold if 300-365 days held + score >= 50 |
| `calculate_tax_adjusted_cost()` | Total switching cost = transaction % + tax % |

**Tax Routes** (`GET /api/v1/tax/*`):
- `/estimate` — Estimate tax for a single hypothetical trade
- `/hold-for-ltcg` — Check if holding for LTCG makes sense given score + days
- `/adjusted-cost` — Full switching cost including tax impact

---

## 8. Position Sizing Utility

**File:** [`src/utils/sizing_utils.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/utils/sizing_utils.py)

`calculate_position_size(atr, current_price, total_capital, remaining_capital, config)`:

```
Constraint order (each narrows the result):

1. ATR Risk-Parity Sizing (primary):
   risk_amount = total_capital × (config.risk_threshold / 100)
   stop_distance = ATR × config.sl_multiplier
   shares = floor(risk_amount / stop_distance)
   position_value = shares × current_price

2. Remaining Capital Cap (spending limit):
   if position_value > remaining_capital:
     shares = floor(remaining_capital / current_price)

3. Concentration Cap (max 25% in one stock):
   max_exposure = total_capital × config.max_concentration_pct
   headroom = max_exposure - existing_position_value
   if position_value > headroom:
     shares = floor(headroom / current_price)

4. Minimum Position Check (after all caps):
   min_position = total_capital × config.min_position_percent
   if position_value < min_position OR shares <= 0:
     return {shares: 0, ...}  ← reject: position too small
```

> **Why 4 constraints?** Risk-parity ensures consistent risk per trade. Remaining-capital prevents overspending. Concentration cap prevents single-stock overexposure. Minimum position rejects capital-constrained scenarios where the position would be ineffectually small.

---

## 9. App Orchestration (Pipeline Runner)

**File:** [`src/api/v1/routes/app_routes.py`](file:///c:/Users/harsh/Documents/GitHub/stocks_screener_v2/src/api/v1/routes/app_routes.py)  
**Blueprint prefix:** `/api/v1/app`

### `POST /api/v1/app/run-pipeline`

Runs the full data pipeline in dependency order. Each step is independently togglable via JSON body params. If any step fails, all downstream steps are skipped.

```
Step 0: Kite Auth    — Validate API token (fail-fast before any Kite calls)
Step 1: Init App     — InitService.initialize_app()    [instruments universe]
Step 2: Market Data  — MarketDataService.update_latest_data_for_all()
Step 3: Indicators   — IndicatorsService.calculate_indicators()
Step 4: Percentiles  — PercentileService.backfill_percentiles()
Step 5: Scores       — ScoreService.generate_composite_scores()
Step 6: Rankings     — RankingService.generate_rankings()
```

Body params: `{init, marketdata, indicators, percentile, score, ranking, historical}`  
All default to `true`. `historical=true` fetches full HISTORY_LOOKBACK instead of incremental.

### `POST /api/v1/app/recalculate?start_date=YYYY-MM-DD`

Deletes and regenerates downstream data from a given date. Used after fixing indicator bugs or changing strategy weights:

```
percentile: delete_after_date(start_date) → backfill_percentiles()
score:      delete_after_date(start_date) → generate_composite_scores()
ranking:    delete_after_date(start_date) → generate_rankings()
```

### `DELETE /api/v1/app/cleanup?start_date=YYYY-MM-DD`

Deletes raw data after a date. Toggle individual tables: `marketdata`, `indicators`, `percentile`, `score`, `ranking`.

### `GET /api/v1/app/logs/stream`

Server-Sent Events (SSE) stream of live pipeline log lines. Browser can open this before triggering a pipeline run to watch progress in real-time.

---

## 10. API Route Reference

Complete endpoint map for all routes **not** covered in the ranking deep dive.

### Actions (`/api/v1/actions`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/generate` | Generate BUY/SELL/SWAP actions for a date |
| `GET` | `/` | List actions for a date |
| `GET` | `/dates` | List all distinct action dates |
| `PUT` | `/<action_id>` | Update action (approve/reject/edit units/price) |
| `POST` | `/approve` | Approve all Pending actions for a date |
| `POST` | `/process` | Process Approved actions → update holdings |
| `POST` | `/reject-all` | Reject all Pending actions (clear unfilled buys) |

### Investments (`/api/v1/investment`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/holdings` | Get holdings for a date |
| `GET` | `/holdings/dates` | List all distinct holding dates |
| `GET` | `/summary` | Portfolio summary with live recalculation |
| `GET` | `/summary/history` | All weekly summaries (equity curve data) |
| `POST` | `/summary/recalculate` | Fix/rebuild all summary records from scratch |
| `GET` | `/trade-journal` | Matched buy/sell pairs with P&L (FIFO) |
| `POST` | `/manual/buy` | Create manual BUY action(s) |
| `POST` | `/manual/sell` | Create manual SELL action |
| `POST` | `/sync-prices` | Update holdings current_price to latest market data |
| `GET` | `/capital-events` | List all capital events |
| `POST` | `/capital-events` | Add capital infusion/withdrawal |
| `POST` | `/start-ticker` | Start Kite WebSocket live price stream |
| `GET` | `/live-prices` | Get current live price snapshot |
| `POST` | `/stop-ticker` | Stop live price streaming |

### Backtest (`/api/v1/backtest`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/run` | Run backtest and return results |
| `GET` | `/history` | List all saved backtest runs |
| `GET` | `/history/<id>` | Get full backtest run data |
| `DELETE` | `/history/<id>` | Delete a backtest run |

### Configuration (`/api/v1/config`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/<config_name>` | Get current strategy config |
| `PUT` | `/<config_name>` | Update config (runtime, no restart needed) |
| `POST` | `/<config_name>` | Create new config |

### Tax Analysis (`/api/v1/tax`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/estimate` | STCG/LTCG tax for a hypothetical trade |
| `GET` | `/hold-for-ltcg` | Should you hold longer to get LTCG rate? |
| `GET` | `/adjusted-cost` | True switching cost (transaction + tax %) |

### App Orchestration (`/api/v1/app`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/run-pipeline` | Run full pipeline (toggleable steps) |
| `POST` | `/recalculate` | Recalculate from a start date |
| `DELETE` | `/cleanup` | Delete raw data after a date |
| `GET` | `/logs/stream` | SSE live log stream |

### Data Read Routes (from ranking deep dive)

| Blueprint | Prefix | Key endpoints |
|---|---|---|
| Market Data | `/api/v1/marketdata` | OHLCV queries |
| Indicators | `/api/v1/indicators` | Indicator lookups |
| Percentile | `/api/v1/percentile` | Factor scores + percentile data |
| Score | `/api/v1/score` | Composite scores |
| Ranking | `/api/v1/ranking` | Weekly ranks |
| Instruments | `/api/v1/instruments` | Universe lookup |
| Index | `/api/v1/index` | Nifty index data |
| Costs | `/api/v1/costs` | Transaction cost calculator |
| Init | `/api/v1/init` | Manual universe re-initialization |

---

## 11. Database Schema — Personal DB

```
┌──────────────────────────────────────────────────────┐
│                    PERSONAL DB                        │
├──────────────────────────────────────────────────────┤
│                                                       │
│  config                                               │
│  ├── config_name (PK-like)                            │
│  ├── initial_capital, risk_threshold, max_positions   │
│  ├── exit_threshold, buffer_percent, sl_multiplier    │
│  └── hard_sl_percent, max_concentration_pct           │
│                                                       │
│  actions                                              │
│  ├── action_id (UUID, PK)                             │
│  ├── action_date, type (buy/sell), reason, symbol     │
│  ├── risk, atr, units, prev_close                     │
│  ├── execution_price, capital                         │
│  ├── status (Pending → Approved | Rejected)           │
│  ├── buy_cost, sell_cost, tax                         │
│  └── Indexes: action_date, symbol, status             │
│                                                       │
│  investment_holdings                                  │
│  ├── symbol + date (composite PK)                     │
│  ├── entry_date, entry_price, avg_price               │
│  ├── units, atr, score                                │
│  ├── entry_sl, current_price, current_sl              │
│  └── Indexes: symbol, date, entry_date                │
│                                                       │
│  investment_summary                                   │
│  ├── date (PK)                                        │
│  ├── starting_capital, sold, bought                   │
│  ├── capital_risk, portfolio_value, portfolio_risk    │
│  ├── gain, gain_percentage, remaining_capital         │
│  └── Index: date                                      │
│                                                       │
│  capital_events                                       │
│  ├── id (auto PK)                                     │
│  ├── date, amount, event_type, note                   │
│  └── Types: 'initial' | 'infusion' | 'withdrawal'    │
│             | 'realized_gain' (auto on sell)          │
│                                                       │
│  backtest_runs                                        │
│  ├── id (auto PK)                                     │
│  ├── run_label, created_at, config_name               │
│  ├── start_date, end_date                             │
│  ├── check_daily_sl, mid_week_buy                     │
│  ├── total_return, max_drawdown, sharpe_ratio         │
│  └── data_dir (path to JSON files on disk)            │
│                                                       │
└──────────────────────────────────────────────────────┘
```

---

## 12. Full System Interaction Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SUNDAY NIGHT / MONDAY MORNING                           │
└─────────────────────────────────────────────────────────────────────────────┘

POST /api/v1/app/run-pipeline
  │
  ├── Step 0: Kite Auth check
  ├── Step 1: InitService     → sync instruments universe with Kite
  ├── Step 2: MarketDataService → fetch Friday's OHLCV for all stocks
  ├── Step 3: IndicatorsService → compute EMAs, RSI, ATR, etc.
  ├── Step 4: PercentileService → factor scores + cross-sectional percentiles
  ├── Step 5: ScoreService     → composite scores + penalty box
  └── Step 6: RankingService   → weekly average → rank 1 = best

POST /api/v1/actions/generate?date=YYYY-MM-DD
  │
  └── ActionGenerator.generate_actions(Monday)
      ├── Read Friday rankings (top 15-20 stocks)
      ├── Read current holdings + capital state
      ├── TradingEngine.generate_decisions() [pure logic]
      │   ├── SELL degraded/SL-hit holdings
      │   ├── BUY vacancies from top-N
      │   └── SWAP: stronger candidate vs weakest holding
      └── Insert Pending actions into actions table

POST /api/v1/actions/approve?date=YYYY-MM-DD
  │
  └── ActionLifecycle.approve_all_actions(Monday)
      ├── Phase 1 — Sells: execute at Monday open, record costs + tax
      └── Phase 2 — Buys:  re-size at Monday open, check capital budget

POST /api/v1/actions/process?date=YYYY-MM-DD
  │
  └── ActionProcessor.process_actions(Monday)
      ├── Phase 1 — Sell: realise PnL, insert capital_event, remove holding
      ├── Phase 2 — Buy:  create new holding OR merge pyramid add
      └── Phase 3 — Hold: trail stop-loss, update score + price

┌─────────────────────────────────────────────────────────────────────────────┐
│                     TUESDAY — THURSDAY (Daily SL)                           │
└─────────────────────────────────────────────────────────────────────────────┘

POST /api/v1/actions/generate?date=YYYY-MM-DD&check_daily_sl=true
  │
  └── ActionGenerator.check_daily_stoploss(day)
      ├── If close < current_sl → Pending SELL for next open
      └── If vacancy opened and mid_week_buy → advance next BUY

      [next morning: approve?date=T+1 → process?date=T+1]

┌─────────────────────────────────────────────────────────────────────────────┐
│                     ANY TIME — Portfolio Monitoring                         │
└─────────────────────────────────────────────────────────────────────────────┘

GET  /api/v1/investment/summary          → Portfolio value, gain, XIRR, risk
GET  /api/v1/investment/trade-journal    → All closed trades (FIFO P&L)
GET  /api/v1/investment/summary/history → Equity curve data (all weeks)
POST /api/v1/investment/sync-prices     → Update holdings to latest close

POST /api/v1/investment/start-ticker    → Kite WebSocket live prices
GET  /api/v1/investment/live-prices     → {symbol: {last_price, change%}}
POST /api/v1/investment/stop-ticker     → Disconnect WebSocket

┌─────────────────────────────────────────────────────────────────────────────┐
│                     BACKTESTING (Any time, isolated DB)                     │
└─────────────────────────────────────────────────────────────────────────────┘

POST /api/v1/backtest/run
  │
  └── BacktestingService.run_backtest(start_date, end_date, config_name)
      │
      └── WeeklyBacktester.run():
          For each Monday in [start, end]:
            ├── reject_pending_actions()
            ├── generate_actions(monday)            [same code as live]
            ├── approve_all_actions(monday)          [same code as live]
            ├── process_actions(monday)              [same code as live]
            └── _process_daily_stoploss(mon, fri)   [Hard SL + Close SL]

          _close_open_positions()   → force-sell all at end_date price
          _build_trades_from_db()   → FIFO-match for trade metrics
          BacktestReportBuilder.build() → text report
          BacktestHistoryRepository.save() → persist to backtest_runs

      Returns: results, summary (CAGR/Sharpe/drawdown/tax), equity_curve, report_path
```

---

*Last updated: 2026-06-07 — Generated from source analysis of `stocks_screener_v2`.*
