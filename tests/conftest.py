import pytest
import pandas as pd
import numpy as np

@pytest.fixture
def sample_ohlcv_data():
    """Create a sample OHLCV DataFrame for testing"""
    dates = pd.date_range(start='2024-01-01', periods=300, freq='B')
    df = pd.DataFrame({
        'open': np.random.uniform(100, 200, 300),
        'high': np.random.uniform(100, 200, 300),
        'low': np.random.uniform(100, 200, 300),
        'close': np.random.uniform(100, 200, 300),
        'volume': np.random.randint(1000, 100000, 300)
    }, index=dates)
    
    # Ensure high is highest, low is lowest
    df['high'] = df[['open', 'close', 'high']].max(axis=1)
    df['low'] = df[['open', 'close', 'low']].min(axis=1)
    
    return df

@pytest.fixture
def sample_indicators_df(sample_ohlcv_data):
    """Create DataFrame with some indicators pre-calculated"""
    df = sample_ohlcv_data.copy()
    df['rsi'] = 60.0
    df['ema_50'] = 150.0
    df['ema_200'] = 140.0
    df['percent_b'] = 0.9
    df['atr'] = 5.0
    return df
