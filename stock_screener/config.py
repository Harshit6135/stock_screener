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
    }
}
