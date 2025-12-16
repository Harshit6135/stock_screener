# Stock Screener V3

A multi-factor momentum screening and portfolio management system for Indian stocks (NSE/BSE). Built with Flask, SQLAlchemy, and Kite Connect API.

## 🌟 Features

- **Multi-Factor Scoring**: Trend, Momentum, Volume, Structure factors
- **Portfolio Management**: Champion vs Challenger rotation, ATR-based position sizing
- **Dual Stop-Loss**: ATR trailing + Hard trailing system
- **Action Generation**: Automated BUY/SELL/SWAP recommendations
- **REST API**: Full Flask-Smorest API with Swagger docs

---

## 📋 Quick Start

```bash
# Clone and setup
git clone <repo-url>
cd stocks_screener_v3

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
stocks_screener_v3/
├── config/            # Flask, app configuration, and indicators
├── data/              # CSV files, instrument lists
├── models/            # SQLAlchemy models
├── schemas/           # Marshmallow schemas
├── resources/         # Flask-Smorest API endpoints
├── router/            # Route handlers (main_router, day0, kite, etc.)
├── services/          # Core services (ranking, portfolio, indicators)
├── templates/         # HTML templates (dashboard.html)
├── utils/             # Helper functions
├── migrations/        # Alembic migrations
├── docs/              # Documentation
└── run.py             # Application entry point
```

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
- Current Investments table view
- Actions table with date filter
- Top 20 rankings view

---

## 📊 Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/latest_rank` | GET | Generate rankings for today |
| `/risk_config` | GET/PUT | Portfolio risk settings |
| `/invested` | GET/POST | Manage positions |
| `/ranking/top20` | GET | Top 20 ranked stocks |
| `/actions/generate` | POST | Generate trade actions |

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
