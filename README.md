# Stock Screener V2

A multi-factor momentum screening and portfolio management system for Indian stocks (NSE/BSE). Built with Flask, SQLAlchemy, and Kite Connect API.

## 🌟 Features

- **Multi-Factor Scoring**: Trend, Momentum, Risk Efficiency, Volume, Structure factors
- **Cross-Sectional Percentile Ranking**: Daily percentile ranks across the universe
- **Composite Score Calculation**: Weighted formula (30% Trend, 30% Momentum, 20% Efficiency, 15% Volume, 5% Structure)
- **Goldilocks Trend Scoring**: Non-linear distance from 200 EMA scoring
- **RSI Regime Mapping**: Non-linear RSI zones for momentum
- **Indian Market Cost Model**: STT, stamp duty, GST, impact cost
- **Tax-Aware Trading**: STCG/LTCG optimization with near-1-year hold bias
- **Portfolio Risk Controls**: Drawdown circuits, sector concentration limits
- **Weekly Rankings**: Friday-based weekly aggregation
- **Multi-Phase Actions**: SELL → SWAP → BUY phases
- **REST API**: Flask-Smorest with Swagger docs
- **Weekly Rankings**: Friday-based weekly aggregation for consistent comparison
- **Portfolio Management**: Champion vs Challenger rotation with buffer threshold
- **Dual Stop-Loss**: ATR trailing + Hard trailing system
- **Multi-Phase Action Generation**: SELL → SWAP → BUY phases for systematic rebalancing
- **Backtesting Engine**: Comprehensive historical simulation with risk monitoring
- **REST API**: Full Flask-Smorest API with Swagger docs

---

## 📋 Quick Start

```bash
# Clone and setup
git clone <repo-url>
cd stocks_screener_v2

# Install with Poetry
poetry install

# Setup secrets
cp local_secrets.example.py local_secrets.py
# Edit local_secrets.py with your Kite API credentials

# Initialize database
make db-init

# Run server
make run
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Setup Guide](docs/SETUP.md) | Installation and configuration |
| [API Reference](docs/API.md) | All API endpoints |
| [Day 0 Setup](docs/DAY0.md) | Initial data loading |
| [Strategy Guide](docs/STRATEGY.md) | Indicators, scoring, trading logic |
| [TODO](docs/TODO.md) | Future work and enhancements |

---

## 🔧 Makefile Commands

```bash
make install      # Install dependencies
make run          # Start Flask server
make db-init      # Initialize DB migrations
make db-migrate   # Create migration
make db-upgrade   # Apply migrations
make test         # Run tests with coverage report
make clean        # Remove cache files
```

---

## 📁 Project Structure

```
stocks_screener_v2/
├── config/                    # Flask, app config, strategy parameters
│   ├── strategies_config.py   # Factor weights and thresholds
│   ├── indicators_config.py   # pandas_ta study definitions
│   └── app_config.py          # Application settings
├── data/                      # CSV files, instrument lists
├── src/
│   ├── api/v1/routes/         # API route handlers
│   │   ├── indicators_routes.py   # Technical indicator endpoints
│   │   ├── instrument_routes.py   # Instrument management
│   │   ├── marketdata_routes.py   # Market data endpoints
│   │   ├── percentile_routes.py   # Percentile ranking endpoints
│   │   ├── ranking_routes.py      # Weekly ranking endpoints
│   │   ├── score_routes.py        # Composite score endpoints
│   │   ├── actions_routes.py      # Trading action endpoints
│   │   ├── investment_routes.py   # Investment/portfolio endpoints
│   │   ├── costs_routes.py        # Transaction cost endpoints
│   │   └── tax_routes.py          # Tax calculation endpoints
│   ├── models/                # SQLAlchemy models
│   │   ├── indicators.py          # Technical indicators (EMA, RSI, PPO, ATR, etc.)
│   │   ├── percentile.py          # Daily percentile ranks
│   │   ├── score.py               # Composite scores
│   │   ├── ranking.py             # Weekly rankings
│   │   ├── investment.py          # Holdings, Actions, Summary
│   │   ├── instruments.py         # Stock instruments
│   │   └── marketdata.py          # OHLCV data
│   ├── repositories/          # Data access layer
│   ├── schemas/               # Marshmallow schemas for API
│   ├── services/              # Business logic layer
│   │   ├── indicators_service.py  # Technical indicator calculations
│   │   ├── percentile_service.py  # Cross-sectional percentile ranking
│   │   ├── score_service.py       # Composite score generation
│   │   ├── ranking_service.py     # Weekly ranking from daily scores
│   │   ├── actions_service.py    # SELL/SWAP/BUY action generation
│   │   ├── factors_service.py     # Goldilocks/RSI factor calculations
│   │   ├── portfolio_controls_service.py  # Drawdown/sector controls
│   │   ├── marketdata_service.py  # Market data processing
│   │   └── init_service.py        # Day 0 initialization
│   └── utils/                 # Helpers
│       ├── finance_utils.py       # XIRR calculation
│       ├── sizing_utils.py        # Multi-constraint position sizing
│       ├── stoploss_utils.py      # Trailing stop-loss logic
│       ├── penalty_box_utils.py   # Stock disqualification rules
│       ├── transaction_costs_utils.py  # Indian market cost model
│       ├── tax_utils.py           # STCG/LTCG calculator
│       ├── ranking_utils.py       # Ranking helpers
│       └── database_manager.py    # Multi-database session management
├── templates/                 # HTML templates (dashboard, backtest)
├── migrations/                # Alembic migrations
├── docs/                      # Documentation
├── scripts/                   # Utility scripts
│   └── pre-commit-hook.sh     # Git hook for workflow enforcement
├── .agent/                    # AI agent instructions
│   ├── instructions.md        # Agent guidelines and compliance checklist
│   └── workflows/             # Mandatory workflows
│       └── default.md         # Default workflow for code changes
├── src/backtesting/           # Backtesting module
│   ├── runner.py              # Weekly backtester with API integration
│   ├── models.py              # Position, BacktestResult, RiskMonitor
│   ├── config.py              # API-based config loader
│   └── api_client.py          # HTTP client for data fetching
└── run.py                     # Application entry point
```

---

## 📈 Scoring System

### Data Pipeline

```
Market Data → Indicators → Percentiles → Scores → Rankings → Actions
```

1. **Market Data**: OHLCV fetched via Kite Connect
2. **Indicators**: Technical indicators calculated (EMA 50/200, RSI, PPO, ATR, Bollinger, etc.)
3. **Percentiles**: Cross-sectional percentile ranks across the universe (0-100)
4. **Scores**: Weighted composite score from percentile ranks
5. **Rankings**: Weekly aggregation (Mon-Fri average) ranked on Fridays
6. **Actions**: SELL/SWAP/BUY decisions based on rankings and portfolio state

### Technical Indicators Calculated

| Indicator | Description |
|-----------|-------------|
| `EMA_50`, `EMA_200` | Exponential Moving Averages |
| `RSI_14` | Relative Strength Index (14-period) |
| `RSI_SIGNAL_EMA_3` | 3-day smoothed RSI |
| `PPO_12_26_9` | Percentage Price Oscillator |
| `PPOH_12_26_9` | PPO Histogram |
| `ROC_10`, `ROC_20` | Rate of Change |
| `ATRr_14` | Average True Range (14-period) |
| `BBU/BBM/BBL_20_2` | Bollinger Bands |
| `percent_b` | Position within Bollinger Bands |
| `ema_50_slope` | EMA 50 slope (trend velocity) |
| `distance_from_ema_200` | % distance from 200 EMA |
| `risk_adjusted_return` | ROC_20 / (ATR/Price) |
| `rvol` | Relative volume (vs 20-day avg) |
| `price_vol_correlation` | 10-day price-volume correlation |

### Composite Score Formula (Current)

```
final_trend = trend_rank × 0.6 + trend_extension_rank × 0.4
final_momentum = momentum_rsi_rank × 0.6 + momentum_ppo_rank × 0.25 + momentum_ppoh_rank × 0.15
final_vol = rvolume_rank × 0.7 + price_vol_corr_rank × 0.3
final_structure = structure_rank × 0.5 + structure_bb_rank × 0.5

composite_score = trend × 0.30 + momentum × 0.25 + efficiency × 0.20 + vol × 0.15 + structure × 0.10
```

### Weekly Rankings

- Aggregates daily composite scores (Mon-Fri)
- Stored with Friday date as anchor
- Used for portfolio decisions and backtesting

---

## 🔄 Action Generation Phases

The `ActionsService` class generates trade actions in three phases:

1. **SELL Phase**: Exit positions with stop-loss hits or score degradation (< exit threshold)
2. **SWAP Phase**: Replace incumbent if challenger beats by buffer (default 50%)
3. **BUY Phase**: Fill vacant slots with top-ranked stocks

---

## 🧪 Backtesting

Run historical backtests using the backtesting module:

```python
from src.backtesting import run_backtest
from datetime import date

results, summary = run_backtest(
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31)
)
```

**Features:**
- Weekly rebalancing aligned with Strategy logic
- ATR-based position sizing and stop-loss
- Risk monitoring with drawdown tracking
- Trade-by-trade analysis with hit rate metrics
- CSV export for results and holdings

**Key Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `INITIAL_CAPITAL` | ₹10,00,000 | Starting capital |
| `RISK_PER_TRADE` | ₹10,000 | Max loss per trade |
| `MAX_POSITIONS` | 10 | Maximum portfolio size |
| `STOP_MULTIPLIER` | 2.0 | ATR multiplier for stop-loss |
| `BUFFER_PERCENT` | 0.5 | Swap threshold (50%) |

---

## 🔗 Data Sources

### Day 0 Stock Lists

| Exchange | URL | Notes |
|----------|-----|-------|
| **NSE** | [Securities Available for Trading](https://www.nseindia.com/static/market-data/securities-available-for-trading) | Download EQUITY_L.csv |
| **BSE** | [List of Scrips](https://www.bseindia.com/corporates/List_Scrips.html) | Select Segment = T |

---

## 🔐 Configuration

Create `local_secrets.py` in root:

```python
KITE_API_KEY = "your_api_key"
KITE_API_SECRET = "your_api_secret"
```

### Strategy Parameters (`config/strategies_config.py`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `trend_strength_weight` | 0.30 | Weight for trend factor |
| `momentum_velocity_weight` | 0.25 | Weight for momentum factor |
| `risk_efficiency_weight` | 0.20 | Weight for efficiency factor |
| `conviction_weight` | 0.15 | Weight for volume factor |
| `structure_weight` | 0.10 | Weight for structure factor |
| `turnover_threshold` | 1 Cr | Minimum daily turnover |
| `atr_threshold` | 2 | ATR multiplier for stops |

---

## 🌐 Web Dashboard

Access at `http://127.0.0.1:5000/` after starting the server.

**Features:**
- Action buttons for screener operations (Day 0, Market Data, Indicators, Rankings)
- Current investments table with XIRR and returns
- Actions table with date filter
- Top 20 rankings view
- Execute trades with actual prices

---

## 📊 API Endpoints

### Core Data Pipeline

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/init/day0` | POST | Initialize with instruments and market data |
| `/marketdata/update` | POST | Fetch latest market data |
| `/indicators/generate` | POST | Calculate technical indicators |
| `/percentile/generate` | POST | Generate percentile ranks |
| `/scores/generate` | POST | Generate composite scores |
| `/ranking/generate` | POST | Generate weekly rankings |

### Score Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/scores/generate` | POST | Generate composite scores incrementally |
| `/scores/recalculate` | POST | Recalculate all composite scores |

### Ranking Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ranking/top20` | GET | Top 20 ranked stocks |
| `/ranking/{date}` | GET | Rankings for specific date |
| `/ranking/generate` | POST | Generate rankings incrementally |
| `/ranking/recalculate` | POST | Recalculate all rankings |

### Actions Endpoints (formerly Strategy)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/actions/generate` | POST | Generate trade actions |
| `/api/v1/actions/backtesting` | POST | Run backtesting simulation |
| `/api/v1/actions/config` | POST | Initialize strategy config |

### Backtest Query Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/indicators/{name}` | GET | Get indicator value by name |
| `/api/v1/marketdata/{symbol}` | GET | Get OHLCV for symbol |
| `/api/v1/score/{symbol}` | GET | Get composite score |
| `/api/v1/costs/roundtrip` | GET | Calculate round-trip transaction costs |
| `/api/v1/costs/buy` | GET | Calculate buy-side costs |
| `/api/v1/costs/sell` | GET | Calculate sell-side costs |
| `/api/v1/costs/position-size` | GET | Calculate ATR-based position size |
| `/api/v1/costs/equal-weight-size` | GET | Calculate equal-weight position |
| `/api/v1/tax/estimate` | GET | Estimate capital gains tax |
| `/api/v1/tax/hold-for-ltcg` | GET | Check if holding for LTCG is beneficial |
| `/api/v1/tax/adjusted-cost` | GET | Calculate tax-adjusted switching cost |

### Investment Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/investment/holdings` | GET | Current portfolio holdings |
| `/investment/actions` | GET | Trade action history |
| `/investment/summary` | GET | Portfolio summary |

See Swagger UI at `/api/v1/swagger` for full interactive documentation.

---

## ⚙️ Risk Configuration

Default settings:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `initial_capital` | ₹1,00,000 | Starting capital |
| `risk_per_trade` | ₹1,000 | Max loss per trade |
| `max_positions` | 15 | Maximum stocks |
| `buffer_percent` | 50% | Swap hysteresis |
| `exit_threshold` | 40 | Score for exit |

---

## 🛠️ Development

```bash
# Install dev dependencies
poetry install --with dev

# Run with reload
make dev

# Format code
make format
```

---

## 📄 License

MIT License - See LICENSE file.

---

**Disclaimer**: This tool is for educational purposes only. Not investment advice.
