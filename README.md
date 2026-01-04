# Stock Screener V2

A multi-factor momentum screening and portfolio management system for Indian stocks (NSE/BSE). Built with Flask, SQLAlchemy, and Kite Connect API.

## 🌟 Features

- **Multi-Factor Scoring**: Trend, Momentum, Volume, Structure factors with configurable weights
- **Composite Score Calculation**: Weighted formula combining trend (60%), momentum (20%), structure (10%), and volume (10%)
- **Weekly Average Scores**: Friday-based weekly aggregation for consistent ranking
- **Portfolio Management**: Champion vs Challenger rotation, ATR-based position sizing
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
| [Setup Guide](docs/SETUP.md) | Detailed installation instructions |
| [API Reference](docs/API.md) | All API endpoints |
| [Day 0 Setup](docs/DAY0.md) | Initial data loading process |
| [Strategy Guide](docs/STRATEGY.md) | Scoring methodology |

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
├── config/                    # Flask, app configuration, strategy parameters
├── data/                      # CSV files, instrument lists
├── src/
│   ├── api/v1/routes/         # API route handlers
│   │   ├── actions_routes.py      # Trade action endpoints
│   │   ├── indicators_routes.py   # Technical indicator endpoints
│   │   ├── instrument_routes.py   # Instrument management
│   │   ├── marketdata_routes.py   # Market data endpoints
│   │   ├── portfolio_routes.py    # Portfolio management
│   │   ├── ranking_routes.py      # Ranking endpoints
│   │   └── score_routes.py        # Composite score endpoints
│   ├── models/                # SQLAlchemy models
│   │   ├── actions.py             # Trade actions
│   │   ├── holdings.py            # Portfolio holdings
│   │   ├── indicators.py          # Technical indicators
│   │   ├── invested.py            # Investment positions
│   │   ├── ranking.py             # Stock rankings
│   │   └── risk_config.py         # Risk configuration
│   ├── repositories/          # Data access layer
│   ├── schemas/               # Marshmallow schemas
│   ├── services/              # Business logic layer
│   │   ├── actions_service.py     # SELL/SWAP/BUY action generation
│   │   ├── indicators_service.py  # Technical indicator calculations
│   │   ├── marketdata_service.py  # Market data processing
│   │   ├── portfolio_service.py   # Portfolio management
│   │   ├── ranking_service.py     # Stock ranking logic
│   │   └── score_service.py       # Composite & weekly avg scores
│   ├── strategies/            # Trading strategies
│   └── utils/                 # Helper functions (stop-loss, position sizing)
├── templates/                 # HTML templates (dashboard.html)
├── migrations/                # Alembic migrations
├── docs/                      # Documentation
├── backtesting_new.py         # Backtesting engine
└── run.py                     # Application entry point
```

---

## 📈 Scoring System

### Composite Score Formula

```
final_trend = trend_rank × 0.6 + trend_extension_rank × 0.2 + trend_start_rank × 0.2
final_momentum = momentum_rank × 0.5 + acceleration_rank × 0.3 + slope_rank × 0.2
final_structure = structure_rank × 1.0
final_volume = volume_rank × 1.0

composite_score = final_trend × 0.6 + final_momentum × 0.2 + final_structure × 0.1 + final_volume × 0.1
```

### Weekly Average Scores

- Calculated every Friday (week-end anchor)
- Aggregates daily composite scores from Monday to Friday
- Used for consistent weekly comparison and backtesting

---

## 🔄 Action Generation Phases

The `ActionsService` generates trade actions in three phases:

1. **SELL Phase**: Exit positions with stop-loss hits or score degradation
2. **SWAP Phase**: Replace incumbent if challenger beats by buffer (default 25%)
3. **BUY Phase**: Fill vacant slots with top-ranked stocks

---

## 🧪 Backtesting

Run historical backtests with `backtesting_new.py`:

```bash
python backtesting_new.py
```

**Features:**
- Weekly rebalancing aligned with ActionsService logic
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

---

## 🌐 Web Dashboard

Access the dashboard at `http://127.0.0.1:5000/` after starting the server.

**Features:**
- Action buttons for all screener operations (Day 0, Market Data, Indicators, Rankings, Generate Actions)
- Current Investments table with XIRR and returns
- Actions table with date filter
- Top 20 rankings view
- Execute trades with actual prices

---

## 📊 API Endpoints

### Score Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/scores/generate` | POST | Generate composite scores incrementally |
| `/scores/recalculate` | POST | Recalculate all composite scores |
| `/scores/avg/generate` | POST | Generate weekly average scores |
| `/scores/avg/recalculate` | POST | Recalculate all weekly averages |

### Ranking Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ranking/top20` | GET | Top 20 ranked stocks |
| `/ranking/generate` | POST | Generate rankings for a date |

### Action Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/actions/generate` | POST | Generate trade actions |
| `/actions/execute` | POST | Execute a trade action |

### Portfolio Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolio/invested` | GET | Get current positions |
| `/portfolio/holdings` | GET | Get holdings |
| `/risk_config` | GET/PUT | Portfolio risk settings |

See [API Reference](docs/API.md) for complete documentation.

---

## ⚙️ Risk Configuration

Default settings (configurable via API):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `initial_capital` | ₹1,00,000 | Starting capital |
| `risk_per_trade` | ₹1,000 | Max loss per trade |
| `max_positions` | 15 | Maximum stocks |
| `buffer_percent` | 25% | Swap hysteresis |
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
