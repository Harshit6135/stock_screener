# Backtesting Engine

> **Last Updated:** 2026-02-16

The **Backtesting Engine** simulates the strategy over historical data to validate performance, drawdowns, and risk metrics. It uses a **separate database** (`backtest.db`) to ensure production data is never touched.

---

## 🔄 Backtest Architecture

```mermaid
flowchart TD
    Config[Backtest Input<br/>Start/End Date, Capital] --> Runner[BacktestRunner]
    
    subgraph Engine["Execution Engine"]
        Runner --> Init[Initialize Backtest DB]
        Init --> Loop{Weekly Loop}
        
        Loop --> Gen[Generate Actions<br/>(Monday)]
        Gen --> Approve[Approve Actions]
        Approve --> Process[Update Holdings]
        
        Process --> DailyChecks{Daily SL Check}
        DailyChecks -- "Hard/Close SL Hit" --> Exit[Sell Intraday/Next Open]
        DailyChecks -- "Vacancy" --> Fill[Fill Buy on Dip]
        
        DailyChecks --> Metrics[Track Daily Equity]
        Metrics --> Loop
    end
    
    Engine --> Output[Results]
    Output --> Report[CSV/Text Report]
    Output --> DB[backtest.db]
    Output --> JSON[Response JSON]
```

---

## 🕹️ Backtest Modes

### 1. Daily SL Mode (`check_daily_sl=True`) — Recommended
Simulates realistic monitoring.
- **Hard SL (Intraday)**: If `Low <= SL * 0.95`, sells immediately at the Hard SL price.
- **Close SL**: If `Close < SL`, sells at **Next Day Open**.
- **Mid-Week Buys**: If a slot opens up mid-week (due to a stop-loss), it attempts to fill it with the next top-ranked stock, provided the price hasn't run up >3% (stale guard).

### 2. Weekly Only Mode (`check_daily_sl=False`)
Simulates a passive "coffee can" style.
- Only checks stops and rankings on **Monday**.
- No mid-week actions.
- Faster, but less realistic for volatile momentum strategies.

---

## 🚀 Running a Backtest

### Via API
**POST** `/api/v1/backtest/run`

```json
{
  "start_date": "2023-01-01",
  "end_date": "2023-12-31",
  "initial_capital": 1000000,
  "config_name": "momentum_config",
  "check_daily_sl": true,
  "mid_week_buy": true
}
```

### Via Dashboard
1. Go to `http://localhost:5000/backtest`
2. Select dates and config.
3. Click "Run Backtest".

---

## 📊 Result Interpretation

The backtest returns a comprehensive report (`reports/Backtest_Report_YYYYMMDD.txt`) and JSON data.

### Key Metrics
- **CAGR**: Compound Annual Growth Rate.
- **Max Drawdown**: Largest peak-to-trough decline.
- **Sharpe Ratio**: Risk-adjusted return (Target > 1.0).
- **Win Rate**: % of profitable trades.
- **Profit Factor**: Gross Profit / Gross Loss.
- **Expectancy**: Average return per trade.

### Trade Journal
Includes every trade with:
- **Entry/Exit Date**
- **Entry/Exit Price**
- **Trigger**: Why it was sold (SL Hit, Ranking Drop, Swap, Target)
- **P&L**: Net profit after transaction costs.

---

## 🛠️ Data Handling

- **Market Data**: Uses the main `market_data` table from the primary DB (read-only).
- **Rankings**: Uses `percentile` and `ranking` tables from primary DB.
- **State**: Creates a temporary `backtest.db` for the run, containing `holdings`, `actions`, `capital_events`, and `summary` tables specifically for the simulation.

> **Note**: Backtesting requires historical market data and rankings to be pre-calculated in the main DB for the simulation period.

---

## 📝 Flow: Daily SL Logic

```mermaid
flowchart TD
    StartDay[Day Start] --> Pending{Pending Sell?}
    Pending -- Yes --> SellOpen[Execute at Open]
    Pending -- No --> CheckLow
    
    CheckLow{Low <= Hard SL?} -- Yes --> SellHard[Execute at Hard SL]
    CheckLow -- No --> CheckClose
    
    CheckClose{Close < SL?} -- Yes (Mon-Thu) --> QueueSell[Queue for Next Open]
    CheckClose -- Yes (Friday) --> Skip[Skip (Weekly Logic Handles)]
    CheckClose -- No --> Hold
    
    SellOpen --> VacancyCheck
    SellHard --> VacancyCheck
    
    VacancyCheck{Vacancy?} -- Yes --> BuyFill[Buy Candidate]
    BuyFill --> EndDay
    Hold --> EndDay
```
