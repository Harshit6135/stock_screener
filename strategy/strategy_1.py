import pandas_ta as ta

# Create a custom strategy
momentum_strategy = ta.Study(
    name="Momentum Strategy",
    description="Combines trend, momentum, and volatility indicators",
    ta=[
        {"kind": "ema", "length": 50},
        {"kind": "ema", "length": 200},
        {"kind": "rsi", "length": 14},
        {"kind": "roc", "length": 10},
        {"kind": "roc", "length": 20},
        {"kind": "sma", "length": 20},
        {"kind": "stoch", "k": 14, "d": 3},
        {"kind": "ppo", "fast": 12, "slow": 26, "signal": 9},
        {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
        {"kind": "bbands", "length": 20, "std": 2},
        {"kind": "atr", "length": 14}
    ]
)

derived_strategy = ta.Study(
    name="Derived Strategy",
    description="Combines trend, momentum, and volatility indicators",
    ta=[
        {"kind": "ema", "length": 3, "close": "RSI_14", "prefix": "RSI_SIGNAL"},
        {"kind": "sma", "length": 20, "close":"volume", "prefix": "VOLUME"},
    ]
)

additional_parameters = {
    "vol_price_lookback": 10,
    "ema_slope_lookback": 5,
}