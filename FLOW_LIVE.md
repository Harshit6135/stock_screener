# Live Trading Flow — Action Generation Only

This diagram shows the **Friday Action Generation** workflow.
All subsequent steps (approve, execute, process) are performed
manually on the trading platform.

```mermaid
sequenceDiagram
    participant Market as "NSE Market"
    participant Data as "Data Pipeline"
    participant API as "API (/actions/generate)"
    participant Screen as "Screener (Scoring)"
    participant DB as "Database"
    participant Admin as "User"

    Note over Market, Screen: **Friday Evening (Post-Market)**

    Market->>Data: Friday Market Data (OHLC, Vol)
    Data->>Screen: Update Indicators & Factors

    Note over Admin, API: **Generation Trigger (Weekend)**

    Admin->>API: `POST /actions/generate?date=NextMonday`
    API->>API: Resolve data_date = get_prev_friday(Monday)
    API->>Screen: Fetch Rankings & Prices for data_date (Friday)
    Screen->>Screen: Calculate SL Sells + New Buys + Swaps
    Screen->>API: Return Action Candidates
    API->>DB: **Insert Pending Actions** (dated Monday)

    Note over Admin, DB: **Review Phase (Weekend)**
    Admin->>DB: Check Pending Actions
    Admin->>Admin: Review & Decide
```

### Key Points

| Aspect | Detail |
|--------|--------|
| **Input** | `date=NextMonday` (e.g., `2025-01-13`) |
| **Data Resolution** | `get_prev_friday(Monday)` → Friday for rankings, market data, indicators |
| **Action Date** | Monday — actions are stamped for Monday execution |
| **SL Types** | **Close-based SL** (trailing, from Friday close) generates SELL actions; **Hard SL** (intraday) is monitored live by the trader |
| **After Generation** | Approve & execute manually on your trading platform Monday morning |
