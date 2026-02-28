# Architecture

> **Last Updated:** 2026-02-16

System architecture, data flow, database schema, and configuration for Stock Screener V2.

---

## System Architecture

```mermaid
flowchart TD
    subgraph Client["Client Layer"]
        DASH[Web Dashboard<br/>HTML Templates]
        SWAGGER[Swagger UI<br/>/swagger-ui]
        CURL[REST Clients<br/>curl / Postman]
    end

    subgraph API["API Layer (Flask-Smorest)"]
        direction TB
        BP1[Init Blueprint]
        BP2[App Orchestration]
        BP3[Config Blueprint]
        BP4[Instruments Blueprint]
        BP5[Market Data Blueprint]
        BP6[Indicators Blueprint]
        BP7[Percentile Blueprint]
        BP8[Score Blueprint]
        BP9[Ranking Blueprint]
        BP10[Actions Blueprint]
        BP11[Investment Blueprint]
        BP12[Costs Blueprint]
        BP13[Tax Blueprint]
        BP14[Backtest Blueprint]
    end

    subgraph Services["Service Layer (Business Logic)"]
        S1[InitService]
        S2[MarketDataService]
        S3[IndicatorsService]
        S4[PercentileService]
        S5[ScoreService / FactorsService]
        S6[RankingService]
        S7[ActionsService / TradingService]
        S8[InvestmentService]
        S9[PortfolioControlsService]
    end

    subgraph Repos["Repository Layer (Data Access)"]
        R[Repositories<br/>SQLAlchemy queries]
    end

    subgraph DB["Database Layer"]
        MAIN[(Main DB<br/>SQLite)]
        BTDB[(Backtest DB<br/>SQLite)]
    end

    subgraph External["External"]
        KITE[Kite Connect API]
        YF[yfinance]
    end

    Client --> API
    API --> Services
    Services --> Repos
    Repos --> DB
    S1 & S2 --> KITE
    S1 --> YF
```

---

## Layered Design

The application follows a strict **Routes → Services → Repositories → Models** layering:

| Layer | Directory | Responsibility |
|-------|-----------|---------------|
| **Routes** | `src/api/v1/routes/` | HTTP handling, request validation (Marshmallow schemas), response formatting. Thin controllers. |
| **Services** | `src/services/` | All business logic: calculations, orchestration, decision-making. No direct DB queries. |
| **Repositories** | `src/repositories/` | Data access: SQLAlchemy queries, bulk inserts, filtering. No business logic. |
| **Models** | `src/models/` | SQLAlchemy ORM table definitions. |
| **Schemas** | `src/schemas/` | Marshmallow schemas for request/response validation and serialization. |
| **Utils** | `src/utils/` | Pure functions: position sizing, stop-loss, transaction costs, tax, metrics. |
| **Config** | `src/config/` | Configuration dataclasses: strategy weights, costs, tax rates, sizing constraints. |

---

## Data Pipeline Flow

The core pipeline transforms raw market data into actionable trade decisions:

```mermaid
flowchart LR
    subgraph Ingest["1. Ingest"]
        CSV[NSE/BSE CSVs] --> INIT[InitService]
        KITE[Kite API] --> MDS[MarketDataService]
    end

    subgraph Calculate["2. Calculate"]
        MDS --> IND[IndicatorsService<br/>20+ technical indicators]
        IND --> PCT[PercentileService<br/>Cross-sectional ranks]
        PCT --> FAC[FactorsService<br/>Goldilocks + RSI regime]
        FAC --> SCR[ScoreService<br/>Weighted composite]
        SCR --> RNK[RankingService<br/>Weekly aggregation]
    end

    subgraph Trade["3. Trade"]
        RNK --> ACT[ActionsService<br/>SELL → SWAP → BUY]
        ACT --> INV[InvestmentService<br/>Holdings management]
    end
```

### Pipeline Steps

| Step | Service | Input | Output | Table |
|------|---------|-------|--------|-------|
| **1. Init** | `InitService` | NSE/BSE CSVs | Filtered stock universe | `instruments`, `master` |
| **2. Market Data** | `MarketDataService` | Kite API | Daily OHLCV | `market_data` |
| **3. Indicators** | `IndicatorsService` | OHLCV | EMA, RSI, PPO, ATR, etc. | `indicators` |
| **4. Percentiles** | `PercentileService` | Indicators | Cross-sectional ranks (0-100) | `percentile` |
| **5. Scores** | `ScoreService` + `FactorsService` | Percentiles + Indicators | Composite score per stock | `composite_score` |
| **6. Rankings** | `RankingService` | Daily scores | Weekly average + rank | `ranking` |
| **7. Actions** | `ActionsService` | Rankings + Holdings | BUY/SELL/SWAP decisions | `actions` |
| **8. Holdings** | `InvestmentService` | Processed actions | Portfolio state | `holdings`, `summary` |

---

## Database Schema

### Main Database (SQLite)

```mermaid
erDiagram
    INSTRUMENTS {
        int instrument_token PK
        string exchange_token
        string tradingsymbol
        string name
        string exchange
    }

    MASTER {
        int id PK
        int instrument_token FK
        string tradingsymbol
        string isin
        string exchange
        float mcap
        float prev_close
    }

    MARKET_DATA {
        int id PK
        int instrument_token FK
        string tradingsymbol
        string exchange
        date date
        float open
        float high
        float low
        float close
        float volume
    }

    INDICATORS {
        int id PK
        int instrument_token FK
        string tradingsymbol
        string exchange
        date date
        float ema_50
        float ema_200
        float rsi_14
        float ppo_12_26_9
        float atrr_14
        float roc_10
        float roc_20
        float roc_60
        float roc_125
        float atr_spike
        float avg_turnover_20d
    }

    PERCENTILE {
        int id PK
        int instrument_token FK
        string tradingsymbol
        date date
        float trend_rank
        float momentum_rank
        float efficiency_rank
        float volume_rank
        float structure_rank
    }

    COMPOSITE_SCORE {
        int id PK
        int instrument_token FK
        string tradingsymbol
        date date
        float composite_score
    }

    RANKING {
        int id PK
        string tradingsymbol
        date ranking_date
        float composite_score
        int rank
    }

    ACTIONS {
        int id PK
        date action_date
        string action_type
        string tradingsymbol
        int units
        float expected_price
        float execution_price
        float amount
        float composite_score
        string status
        string reason
    }

    HOLDINGS {
        int id PK
        string tradingsymbol
        int instrument_token
        date buy_date
        float buy_price
        int num_shares
        float current_stop_loss
        float atr_at_entry
    }

    SUMMARY {
        int id PK
        date summary_date
        float portfolio_value
        float remaining_capital
        float total_invested
        float xirr
    }

    CONFIG {
        int id PK
        string config_name
        float initial_capital
        float risk_per_trade
        int max_positions
        float buffer_percent
        float exit_threshold
        float stop_loss_multiplier
    }

    CAPITAL_EVENTS {
        int id PK
        date date
        float amount
        string event_type
        string note
    }

    BACKTEST_RUNS {
        int id PK
        string run_label
        datetime created_at
        string config_name
        date start_date
        date end_date
        boolean check_daily_sl
        boolean mid_week_buy
        float total_return
        float max_drawdown
        float sharpe_ratio
        string data_dir
    }

    INSTRUMENTS ||--o{ MARKET_DATA : has
    INSTRUMENTS ||--o{ INDICATORS : has
    INSTRUMENTS ||--o{ PERCENTILE : has
    INSTRUMENTS ||--o{ COMPOSITE_SCORE : has
    INSTRUMENTS ||--o{ HOLDINGS : held_in
```

### Backtest Database

A separate SQLite database (`backtest.db`) is created per backtest run. It mirrors the main DB schema for `holdings`, `actions`, and `summary` tables, allowing isolated simulation without affecting production data.

---

## Configuration System

### Strategy Configuration Classes

All configuration lives in `src/config/strategies_config.py` as dataclasses:

| Class | Purpose | Key Parameters |
|-------|---------|---------------|
| `StrategyParameters` | Factor weights for composite score | `trend_strength_weight=0.30`, `momentum_velocity_weight=0.25`, `risk_efficiency_weight=0.20` |
| `TransactionCostConfig` | Indian market fees | STT, stamp duty, GST, exchange, SEBI, IPF, DP charges |
| `ImpactCostConfig` | Market impact tiers | 4 tiers based on order size vs ADV |
| `PenaltyBoxConfig` | Score disqualification rules | Below EMA200, ATR spike, illiquid |
| `PositionSizingConfig` | Position sizing constraints | Risk per trade, concentration limit, ADV limit |
| `PortfolioControlConfig` | Portfolio-level risk controls | Drawdown pause/reduce, sector limits |
| `TaxConfig` | Capital gains tax (India) | STCG 20%, LTCG 12.5%, ₹1.25L exemption |
| `ChallengerConfig` | Swap decision parameters | Exit threshold, buffer percent |
| `GoldilocksConfig` | Non-linear trend scoring zones | 4 distance-from-EMA zones |
| `RSIRegimeConfig` | Non-linear RSI scoring zones | 5 RSI regime zones |
| `BacktestConfig` | Backtest defaults | Initial capital, max positions |

### Runtime Configuration API

Strategy parameters can also be managed at runtime via the `/api/v1/config/{config_name}` endpoints (GET/PUT/POST). These are stored in the `config` database table and override the static defaults.

---

## API Blueprint Organization

The Flask app registers 14 blueprints in `run.py`, grouped by function:

```mermaid
flowchart TD
    subgraph System["System & Config"]
        INIT["/api/v1/init"]
        APP["/api/v1/app"]
        CFG["/api/v1/config"]
    end

    subgraph DataPipeline["Data Pipeline"]
        INST["/api/v1/instruments"]
        MD["/api/v1/market_data"]
        INDI["/api/v1/indicators"]
        PCT["/api/v1/percentile"]
        SCR["/api/v1/score"]
        RNK["/api/v1/ranking"]
    end

    subgraph TradingOps["Trading"]
        ACT["/api/v1/actions"]
        INV["/api/v1/investment"]
    end

    subgraph AnalysisOps["Analysis"]
        COST["/api/v1/costs"]
        TAX["/api/v1/tax"]
        BT["/api/v1/backtest"]
    end
```

See [API Reference](API.md) for the complete endpoint documentation.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Separate backtest DB** | Isolates simulation state from production holdings; allows parallel runs |
| **ActionsService reuse in backtest** | Same trading logic for live and backtest ensures consistency |
| **Friday-anchored rankings** | Weekly rank stability; all dates normalized to nearest Friday |
| **Three-phase action generation** | SELL first frees capital, SWAP optimizes, BUY fills vacancies — order matters |
| **Hard penalty exclusions** | Immediate score of 0 for stocks below EMA 50, EMA 200, low liquidity, or penny stocks |
| **Multi-constraint position sizing** | Most restrictive of ATR risk / minimum value wins |
| **Repository pattern** | Clean separation between business logic and DB queries; enables DB injection for backtest |
