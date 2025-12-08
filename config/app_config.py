import os
import sys

# Add project root to sys.path to allow importing local_secrets
# This config file is in project_root/config/
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from local_secrets import KITE_API_KEY, KITE_API_SECRET
except ImportError:
    # Fallback or empty if file not found (e.g. in CI/CD without secrets)
    KITE_API_KEY = "YOUR_API_KEY"
    KITE_API_SECRET = "YOUR_API_SECRET"
    print("WARNING: local_secrets.py not found. Using placeholder API keys.")

# --- STRATEGY CONTROL PANEL ---
CONFIG = {
    "trend": {
        "short_ma": 50,    # The "Fast" Trend Line
        "long_ma": 200     # The "Slow" Trend Line (The Sandbox floor)
    },
    "momentum": {
        "rsi_period": 14,
        "rsi_threshold": 48,
        "rsi_smooth": 9,      # NEW: To calculate RSI Trend (Signal line)
        "roc_period": 10      # NEW: Velocity check
    },
    "stochastic": {           # NEW SECTION
        "k_period": 14,
        "d_period": 3,
        "overbought": 80,
        "oversold": 20
    },
    "squeeze": {
        "bb_window": 20,
        "bb_std": 2,
        "lookback_days": 125, # 6 months (approx 125 trading days)
        "threshold_pct": 0.15 # CHANGED: Increased from 0.10.
                              # 10% is extremely tight (rare). 15-20% captures "tight enough" consolidations.
    },
    "gps": { # MACD Settings
        "fast": 12,
        "slow": 26,
        "signal": 9
    },
    "volume": {
        "short_ema": 5,   # Weekly Interest
        "long_ema": 20    # Monthly Interest
    },
    "risk": {
        "account_size": 100000,   # Example: $100,000 Portfolio
        "risk_per_trade": 0.01,   # Risking 1% ($1,000) per trade
        "atr_multiplier": 2.0,    # Stop Loss distance (2x ATR)
        "atr_period": 14          # Standard lookback for volatility
    },
    "kite": {
        "api_key": KITE_API_KEY,
        "api_secret": KITE_API_SECRET,
        "redirect_url": "http://127.0.0.1"
    }
}
