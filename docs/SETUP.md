# Setup Guide

> **Last Updated:** 2026-05-03

Complete guide to setting up the Stock Screener V2 environment on Windows, Linux, or macOS.

---

## ✅ Prerequisites

Before starting, ensure you have:

1. **Python 3.13+** — [Download Python](https://www.python.org/downloads/)
2. **Poetry** — [Install Poetry](https://python-poetry.org/docs/#installation)
3. **Git** — [Download Git](https://git-scm.com/downloads)
4. **Kite Connect API Account**:
   - API Key & Secret from [Zerodha Developers](https://kite.trade/)
   - Active subscription required for live market data (₹2,000/month)

---

## 🛠️ Installation

### 1. Clone Repository

```bash
git clone <repo-url>
cd stocks_screener_v2
```

### 2. Install Dependencies

```bash
poetry install
```

### 3. Activate Virtual Environment

```bash
poetry shell
```

---

## 🔐 Configuration

### Secrets File

Create `local_secrets.py` from the example template. This file is `.gitignore`d and will never be committed.

```bash
cp local_secrets.example.py local_secrets.py
```

Then edit `local_secrets.py` and fill in your Kite API credentials:

```python
KITE_API_KEY = "your_api_key_here"
KITE_API_SECRET = "your_api_secret_here"
KITE_TOTP_SECRET = ""   # Optional: for auto-login TOTP
```

---

## 🗄️ Database Setup

The project uses **SQLite** with **Flask-Migrate (Alembic)** for schema management.

### Using Makefile (Recommended)

```bash
make setup   # Runs install + db-init + db-migrate + db-upgrade in one shot
```

Or step-by-step:

```bash
make db-init      # Initialise migrations/ folder
make db-migrate   # Generate migration script from models
make db-upgrade   # Apply migrations to instance/stocks.db
```

### Manual Setup

```bash
# Windows PowerShell
$env:FLASK_APP = "run.py"

# Linux / macOS
export FLASK_APP=run.py

flask db init
flask db migrate -m "Initial schema"
flask db upgrade
```

The database file is created at `instance/stocks.db`.

---

## 🚀 Running the Application

### Development (with auto-reload)

```bash
make dev
# OR
poetry run python run.py
```

The server starts at **http://127.0.0.1:5000** using **Waitress** (production-grade, multi-threaded). Auto-reload is not available with Waitress — restart the process manually after code changes, or use Flask's built-in dev server for active development:

```bash
flask run --debug
```

### Production

The application uses Waitress by default (configured in `run.py` with 3 threads and a 600-second channel timeout for SSE). No additional server configuration is needed beyond setting environment-appropriate secrets.

---

## ✅ Verification

After starting the server, run these checks:

**1. Check the dashboard loads:**
Open `http://localhost:5000/` in a browser.

**2. Confirm the config endpoint responds:**

```bash
curl http://localhost:5000/api/v1/config/momentum_config
```

Expected: a JSON response with strategy parameters.

**3. Browse the auto-generated API docs:**
Open `http://localhost:5000/api/v1/swagger-ui` in a browser.

> ⚠️ The `/api/v1/init/` endpoint only accepts `POST` requests — a bare `GET` will return `405 Method Not Allowed`. Use the dashboard button or `curl -X POST http://localhost:5000/api/v1/init/` after placing the required CSV files in `data/`.

---

## 📋 Makefile Reference

| Command | Description |
|---------|-------------|
| `make install` | Install dependencies via Poetry |
| `make run` | Start Flask app (Waitress production mode) |
| `make dev` | Start with debug/reload via Flask dev server |
| `make test` | Run pytest suite with coverage |
| `make format` | Format code (Black + isort) |
| `make lint` | Check code style (Flake8) |
| `make clean` | Remove `__pycache__` and artifacts |
| `make db-init` | Initialize Alembic migrations folder |
| `make db-migrate` | Generate new migration script |
| `make db-upgrade` | Apply pending migrations to DB |
| `make db-reset` | **DANGER**: Wipes DB and re-initializes from scratch |
| `make setup` | Full setup: install + db-init + db-migrate + db-upgrade |

---

## ❓ Troubleshooting

### `Poetry not found`
Ensure the Poetry binary directory is on your `PATH`:
- **Windows**: `%APPDATA%\Python\Scripts`
- **Linux/macOS**: `$HOME/.local/bin`

### `Kite Connect Error`
- Verify API Key/Secret in `local_secrets.py`.
- Ensure your Kite Connect app is active on [kite.trade](https://kite.trade/).
- You must complete the OAuth login flow (visit the login URL) before making API calls — the access token expires daily.

### `Database Errors (no such table)`
Run `make db-upgrade` to apply any pending migrations. If the DB is corrupted, delete the `instance/` folder and run `make db-reset`.

### `ModuleNotFoundError: No module named 'src'`
Ensure you are running commands from the **project root directory** and that `poetry install` completed without errors.

### `yfinance Timeout during Init`
The Day 0 initialization fetches market cap data from yfinance in batches. If it times out, check your internet connection and retry. The script has built-in retries but very slow connections may still fail. See [Day 0 Setup](DAY0.md).
