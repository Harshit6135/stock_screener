import pandas_ta as ta

ema_strategy = ta.Study(
    name="EMA Strategy",
    description="This strategy calculates 200 days EMA",
    cores=0,
    ta=[
        {"kind": "ema", "length": 200},
    ]
)

# Create a custom strategy
momentum_strategy = ta.Study(
    name="Momentum Strategy",
    description="Combines trend, momentum, and volatility indicators",
    cores=0,
    ta=[
        {"kind": "ema", "length": 50},
        {"kind": "rsi", "length": 14},
        {"kind": "roc", "length": 10},
        {"kind": "roc", "length": 20},
        {"kind": "roc", "length": 60},
        {"kind": "roc", "length": 125},
        {"kind": "sma", "length": 20},
        {"kind": "stoch", "k": 14, "d": 3},
        {"kind": "ppo", "fast": 12, "slow": 26, "signal": 9},
        {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
        {"kind": "bbands", "length": 20, "std": 2},
        {"kind": "atr", "length": 14},
        {"kind": "sma", "length": 20, "close":"volume", "prefix": "VOL"},
        {"kind": "ema", "length": 20, "close": "avg_turnover", "prefix": "AVG_TURNOVER"}

    ]
)

derived_strategy = ta.Study(
    name="Derived Strategy",
    description="Derived columns from momentum strategy",
    cores=0,
    ta=[
        {"kind": "ema", "length": 3, "close": "RSI_14", "prefix": "RSI_SIGNAL"}
    ]
)

additional_parameters = {
    "vol_price_lookback": 10,
    "ema_slope_lookback": 5,
    "truncate_days": 365,
    "ema_200_lookback": 900
}