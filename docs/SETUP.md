# Setup Guide

## Prerequisites

- **Python 3.13+**
- **Poetry** (package manager)
- **Kite Connect API** credentials from [Zerodha Developers](https://kite.trade/)

---

## Installation

### 1. Install Poetry

```bash
# Windows (PowerShell)
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -

# Linux/macOS
curl -sSL https://install.python-poetry.org | python3 -
```

### 2. Clone Repository

```bash
git clone <repo-url>
cd stocks_screener_v3
```

### 3. Install Dependencies

```bash
# Install all dependencies
poetry install

# Activate virtual environment
poetry shell
```

### 4. Configure Secrets

```bash
# Create secrets file
cp local_secrets.example.py local_secrets.py

# Edit with your credentials
```

**local_secrets.py:**
```python
KITE_API_KEY = "your_api_key_here"
KITE_API_SECRET = "your_api_secret_here"
```

### 5. Initialize Database

```bash
# Set Flask app
$env:FLASK_APP = "run.py"  # Windows
export FLASK_APP=run.py     # Linux/Mac

# Initialize migrations
flask db init
flask db migrate -m "Initial"
flask db upgrade
```

Or use Makefile:
```bash
make db-init
```

### 6. Run Application

```bash
# Development server
poetry run python run.py

# Or with make
make run
```

Server runs at: http://127.0.0.1:5000

---

## Verify Installation

```bash
# Check risk config endpoint
curl http://localhost:5000/risk_config

# Expected response
{
  "initial_capital": 100000.0,
  "risk_per_trade": 1000.0,
  ...
}
```

---

## Troubleshooting

### Poetry not found
Add Poetry to PATH:
```bash
# Windows
$env:Path += ";$env:APPDATA\Python\Scripts"
```

### Flask not found
Ensure virtual environment is active:
```bash
poetry shell
```

### Database errors
Delete and reinitialize:
```bash
rm -rf migrations instance
make db-init
```
