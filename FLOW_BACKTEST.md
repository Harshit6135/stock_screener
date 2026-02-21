# Backtesting Flow (`runner.py`)

Two modes available via `check_daily_sl` parameter.

---

## Mode 1: Daily SL (`check_daily_sl=True`) — Recommended

Full intra-week stop-loss monitoring with mid-week vacancy fills.

```mermaid
flowchart TD
    Start([Start Backtest]) --> Init["Init: Load Config, Data, Risk Monitor"]
    Init --> LoopStart{"Loop: Every Monday"}
    
    subgraph Weekly_Cycle [Weekly Logic]
        LoopStart -->|Start of Week| Reject["0. Reject Leftover Pending Actions"]
        Reject --> GenStep["1. Generate Actions (Monday date)"]
        GenStep --> GenActions["generate_actions internally resolves<br>Friday via get_prev_friday()"]
        GenActions --> CorrectPx["Correct Prices → Monday Open"]
        CorrectPx --> Approve["2. Approve Actions (capital-aware)"]
        Approve --> Process["3. Process Actions → Update Holdings"]
        
        Process --> DailyLoop{"Daily Loop (Mon→Fri)"}
        
        DailyLoop -->|Each Day| PendingSell{"Pending Close SL<br>from yesterday?"}
        PendingSell -- Yes --> ExecSell["Execute at Today's Open"]
        PendingSell -- No --> DayCheck
        ExecSell --> DayCheck["Intraday Check"]
        
        DayCheck --> HardSL{"Low ≤ Hard SL?"}
        HardSL -- Yes --> SellHard["**Sell at Hard SL Price**"]
        HardSL -- No --> IsFriday{"Is Friday?"}
        
        IsFriday -- No --> CloseSL{"Close < SL?"}
        CloseSL -- Yes --> QueueSell["Queue for Next Day's Open"]
        CloseSL -- No --> VacancyCheck
        
        IsFriday -- Yes --> FriNote["**Skip Close SL**<br>(handled by next generate_actions)"]
        FriNote --> VacancyCheck
        
        SellHard --> VacancyCheck
        QueueSell --> VacancyCheck
        
        VacancyCheck{"Vacancy Exists?"}
        VacancyCheck -- Yes --> StaleCheck{"Price > 3% above Signal?"}
        StaleCheck -- Yes --> SkipBuy["**Stale: Skip Buy**"]
        StaleCheck -- No --> FillBuy["**Fill Pending Buy at Close**"]
        VacancyCheck -- No --> NextDay
        SkipBuy --> NextDay
        FillBuy --> NextDay
        
        NextDay --> DailyLoop
    end
    
    DailyLoop -->|Week End| Metrics["Calculate Weekly Metrics"]
    Metrics --> Result[Store Weekly Result]
    Result --> LoopStart
    
    LoopStart -->|"End Date Reached"| End([End Backtest])

    style SellHard fill:#f9f,stroke:#333
    style ExecSell fill:#f9f,stroke:#333
    style QueueSell fill:#ff9,stroke:#333
    style SkipBuy fill:#aaa,stroke:#333
    style FillBuy fill:#9f9,stroke:#333
```

---

## Mode 2: Weekly SL (`check_daily_sl=False`)

SL checks only at weekly rebalance via `generate_actions`. No intra-week monitoring.

```mermaid
flowchart TD
    Start([Start Backtest]) --> Init["Init: Load Config, Data, Risk Monitor"]
    Init --> LoopStart{"Loop: Every Monday"}
    
    subgraph Weekly_Cycle [Weekly Logic]
        LoopStart -->|Start of Week| Reject["0. Reject Leftover Pending Actions"]
        Reject --> GenStep["1. Generate Actions (Monday date)"]
        GenStep --> GenActions["generate_actions internally resolves<br>Friday via get_prev_friday()"]
        GenActions --> CorrectPx["Correct Prices → Monday Open"]
        CorrectPx --> Approve["2. Approve Actions (capital-aware)"]
        Approve --> Process["3. Process Actions → Update Holdings"]
    end
    
    Process --> Metrics["Calculate Weekly Metrics"]
    Metrics --> Result[Store Weekly Result]
    Result --> LoopStart
    
    LoopStart -->|"End Date Reached"| End([End Backtest])
```

---

## Key Design Decisions

| Aspect | Behaviour |
|--------|-----------|
| **Date Resolution** | Runner passes Monday; `generate_actions` internally calls `get_prev_friday()` for rankings, market data, indicators |
| **Hard SL** | `low ≤ SL × (1 − hard_sl_pct)` → sell at hard SL price (same day) |
| **Close SL (Mon-Thu)** | `close < SL` → sell at next day's open |
| **Friday Close SL** | Handled by `generate_actions` on next Monday (TradingEngine detects `fresh_sl ≥ close`) |
| **Mid-week Buy Fill** | Every day checks for vacancy; 3% stale guard prevents chasing rallied stocks |
| **Pending Rejection** | Unfilled pending buys rejected at start of next week |
| **Execution Prices** | Monday: corrected to open; Daily SL: hard SL at SL price, close SL at next open |
