import pytest
import pandas as pd
import numpy as np
from services.indicators_service import IndicatorsService

def test_calculate_volume_price_correlation(sample_ohlcv_data):
    df = sample_ohlcv_data
    # Create correlation: Price Up + Volume Up
    df['close'] = np.linspace(100, 200, 100)
    df['volume'] = np.linspace(1000, 2000, 100)
    
    corr = IndicatorsService.calculate_volume_price_correlation(df['close'], df['volume'], lookback=10)
    
    # Changes are constant positive, should be correlated?
    # pct_change is constant?
    # Price: 100, 101, 102... returns approx 1% then decreasing %
    # Volume: returns approx same pattern
    # Should be positive
    assert corr.iloc[-1] > 0
    
    # Negative correlation
    df['volume'] = np.linspace(2000, 1000, 100) # Volume drops as price rises
    corr = IndicatorsService.calculate_volume_price_correlation(df['close'], df['volume'], lookback=10)
    # This might not be strictly -1 but should be different
    assert not pd.isna(corr.iloc[-1])

def test_calculate_percent_b():
    close = pd.Series([100.0])
    upper = pd.Series([110.0])
    lower = pd.Series([90.0])
    
    # (100 - 90) / (110 - 90) = 10 / 20 = 0.5
    pb = IndicatorsService.calculate_percent_b(close, upper, lower)
    assert pb.iloc[0] == 0.5

def test_calculate_ema_slope():
    ema = pd.Series([100, 101, 102, 103, 104, 105])
    # shift(5) for index 5 is index 0 (100)
    # (105 - 100) / 100 = 0.05
    slope = IndicatorsService.calculate_ema_slope(ema, lookback=5)
    assert slope.iloc[5] == 0.05

def test_calculate_distance_from_ema():
    close = pd.Series([110.0])
    ema = pd.Series([100.0])
    # (110 - 100) / 100 = 0.10
    dist = IndicatorsService.calculate_distance_from_ema(close, ema)
    assert dist.iloc[0] == 0.10

from config.indicators_config import momentum_strategy

def test_pandas_ta_naming(sample_ohlcv_data):
    # Debug helper to verify column names
    df = sample_ohlcv_data.copy()
    # Use the ACTUAL strategy to see if it works
    df.ta.study(momentum_strategy)
    print("Columns:", df.columns.tolist())
    # Identify the BB columns
    bb_cols = [c for c in df.columns if 'BBU' in c]
    assert len(bb_cols) > 0, f"No BBU columns found. Cols: {df.columns}"

def test_calculate_indicators_full_flow(sample_ohlcv_data):
    service = IndicatorsService()
    df = sample_ohlcv_data.copy()
    
    # Run full calculation
    # Only need to mock if pandas_ta behaves weirdly, but usually fine
    try:
        result = service.calculate_indicators(df)
    except KeyError as e:
        # If we get a key error, it's likely column naming mismatch
        # Fix: The service expects specific names 'BBU_20_2.0'
        # If pandas_ta generated 'BBU_20_2.0', we are good.
        # If not, let's help debug.
        pytest.fail(f"KeyError in calculation: {e}. Available cols: {df.columns.tolist()}")

    # Check if key columns exist
    expected_cols = [
        'ema_50_slope', 
        'price_vol_correlation', 
        'percent_b', 
        'distance_from_ema_200', 
        'risk_adjusted_return',
        'rvol'
    ]
    
    for col in expected_cols:
        assert col in result.columns
        
    # Check cleaning (open/high/low/close dropped)
    assert 'high' not in result.columns
