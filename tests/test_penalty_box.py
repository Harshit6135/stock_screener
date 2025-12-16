import pytest
import pandas as pd
import pandas_ta as ta
from utils.penalty_box import apply_penalty_box

def test_apply_penalty_box_trend():
    # Setup DF with close price below 200 EMA
    dates = pd.date_range(start='2024-01-01', periods=210) # Enough for 200 EMA
    df = pd.DataFrame({
        'close': [100.0] * 210,
        'high': [105.0] * 210,
        'low': [95.0] * 210
    }, index=dates)
    
    # Make the last price drop significantly
    df.iloc[-1, df.columns.get_loc('close')] = 50.0 
    # 200 EMA will be ~100, price 50 -> Broken trend
    
    scores = pd.Series([100.0] * 210, index=dates)
    
    penalized = apply_penalty_box(df, scores)
    
    # Last item should be penalized
    assert penalized.iloc[-1] == 0.0

def test_apply_penalty_box_atr_spike():
    # Setup DF with flat range (ATR -> 0 or very low)
    dates = pd.date_range(start='2024-01-01', periods=50)
    df = pd.DataFrame({
        'high': [100.0] * 50,
        'low': [100.0] * 50,
        'close': [100.0] * 50
    }, index=dates)
    
    # Create massive spike in last few days to pump ATR
    # Need sustained spike because ATR is smoothed
    for i in range(1, 4):
        idx = -i
        df.iloc[idx, df.columns.get_loc('high')] = 200.0
        df.iloc[idx, df.columns.get_loc('low')] = 50.0
    
    scores = pd.Series([100.0] * 50, index=dates)
    
    penalized = apply_penalty_box(df, scores)
    
    # Spike should kill score
    assert penalized.iloc[-1] == 0.0
    
def test_liquidity_trap():
    dates = pd.date_range(start='2024-01-01', periods=50)
    df = pd.DataFrame({
        'close': [100.0] * 50,
        'high': [100.0] * 50,
        'low': [100.0] * 50,
        'turnover': [1000000.0] * 50 # 10 Lakhs < 5 Cr
    }, index=dates)
    
    scores = pd.Series([100.0] * 50, index=dates)
    penalized = apply_penalty_box(df, scores)
    
    assert penalized.iloc[0] == 0.0
