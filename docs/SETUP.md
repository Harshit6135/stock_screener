# Setup Guide

> **Last Updated:** 2026-02-16

Complete guide to setting up the Stock Screener V2 environment on Windows, Linux, or macOS.

---

## ✅ Prerequisites

Before starting, ensure you have:

1. **Python 3.13+**: [Download Python](https://www.python.org/downloads/)
2. **Poetry**: [Install Poetry](https://python-poetry.org/docs/#installation)
3. **Git**: [Download Git](https://git-scm.com/downloads)
4. **Kite Connect API Account**: 
   - API Key & Secret from [Zerodha Developers](https://kite.trade/)
   - Active subscription (₹2000/month) required for market data

---

## 🛠️ Installation

### 1. Clone Repository

```bash
git clone <repo-url>
cd stocks_screener_v2
```

### 2. Install Dependencies

Using **Poetry** (recommended):

```bash
# Install production + dev dependencies
poetry install

# SQLCipher support (optional, if needed for encrypted DBs)
# poetry install --extras "sqlcipher"
```

### 3. Activate Virtual Environment

```bash
poetry shell
```

---

## 🔐 Configuration

### 1. Secrets File

Create a `local_secrets.py` file in the project root. This file is `.gitignore`d to prevent accidental commits.

```bash
# Copy example template
cp local_secrets.example.py local_secrets.py
```

Edit `local_secrets.py`:

```python
# local_secrets.py

KITE_API_KEY = "your_zm_api_key_here"
KITE_API_SECRET = "your_zm_api_secret_here"

# Optional: TOTP secret for auto-login (if implemented)
KITE_TOTP_SECRET = ""
```

---

## 🗄️ Database Setup

The project uses **SQLite** by default. You need to initialize the migrations folder and apply the schema.

### Using Makefile (Recommended)

```bash
# Initialize DB, migrate, and upgrade in one go
make setup

# OR step-by-step:
make db-init      # Create migrations/ folder
make db-migrate   # Generate migration script
make db-upgrade   # Apply to instance/stocks.db
```

### Manual Setup

```bash
# Set FLASK_APP environment variable
# Windows PowerShell
$env:FLASK_APP = "run.py"

# Linux / Mac
export FLASK_APP=run.py

# Run Flask-Migrate commands
flask db init
flask db migrate -m "Initial schema"
flask db upgrade
```

---

## 🚀 Running the Application

### Development Server

Starts the Flask server with hot-reloading enabled.

```bash
# Using Makefile
make dev

# OR using Poetry
poetry run python run.py
```

Server will be available at: **http://127.0.0.1:5000**

### Production Server

For production deployment (e.g., using Gunicorn):

```bash
# Example Gunicorn command
gunicorn -w 4 -b 0.0.0.0:5000 run:app
```

---

## ✅ Verification

Run these commands to verify everything is working:

1. **Check Status Endpoint**:
   ```bash
   curl http://localhost:5000/api/v1/init/
   # Expected: 200 OK or 201 Created
   ```

2. **Check Risk Config**:
   ```bash
   curl http://localhost:5000/api/v1/config/momentum_config
   # Expected: JSON response with strategy parameters
   ```

---

## 📋 Makefile Reference

| Command | Description |
|---------|-------------|
| `make install` | Install dependencies via Poetry |
| `make run` | Run Flask app (standard mode) |
| `make dev` | Run Flask app (debug/reload mode) |
| `make test` | Run pytest suite with coverage |
| `make format` | Format code (Black + Isort) |
| `make lint` | Check code style (Flake8) |
| `make clean` | Remove `__pycache__` and artifacts |
| `make db-reset` | **DANGER**: Wipes DB and re-initializes |

---

## ❓ Troubleshooting

### 1. `Poetry not found`
- Ensure Poetry bin directory is in your `PATH`.
- Windows: `%APPDATA%\Python\Scripts`
- Linux/Mac: `$HOME/.local/bin`

### 2. `Kite Connect Error`
- Verify API Key/Secret in `local_secrets.py`.
- Ensure your Kite Connect app is active.
- Check internet connection.

### 3. Database Errors (`no such table`)
- Run `make db-upgrade` to ensure migrations are applied.
- Delete `instance/` folder and run `make db-reset` to start fresh.

### 4. `ModuleNotFoundError: No module named 'src'`
- Ensure you are running commands from the project root.
- Ensure `poetry install` completed successfully.
