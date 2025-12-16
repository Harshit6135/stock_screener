import pandas as pd
import pandas_ta as ta
import numpy as np
from config.indicators_config import momentum_strategy, derived_strategy

# Mock Data
dates = pd.date_range(start='2024-01-01', periods=300, freq='B')
df = pd.DataFrame({
    'open': np.random.uniform(100, 200, 300),
    'high': np.random.uniform(100, 200, 300),
    'low': np.random.uniform(100, 200, 300),
    'close': np.random.uniform(100, 200, 300),
    'volume': np.random.randint(1000, 100000, 300)
}, index=dates)

import sys

# Redirect stdout to file
log_file = open("debug_output.log", "w")
sys.stdout = log_file
sys.stderr = log_file

print("Initial Columns:", df.columns.tolist())

# Run Momentum Strategy
print("\nRunning Momentum Strategy...")
try:
    df.ta.study(momentum_strategy)
    print("Success. New Columns:", [c for c in df.columns if c not in ['open','high','low','close','volume']])
except Exception as e:
    print("Failed Momentum:", e)

# Run Derived Strategy
print("\nRunning Derived Strategy...")
try:
    df.ta.study(derived_strategy)
    print("Success. New Columns:", [c for c in df.columns if c not in ['open','high','low','close','volume']])
except Exception as e:
    print("Failed Derived:", e)

# Check specific columns needed by service
required = ['BBU_20_2.0', 'BBL_20_2.0', 'EMA_50', 'EMA_200', 'RSI_14', 'VOLUME_SMA_20']
missing = [c for c in required if c not in df.columns]
print("\nMissing Required Columns:", missing)

# Check keys used in service
print("\nService Logic Check:")
try:
    # Service logic mimic
    df['percent_b'] = (df['close'] - df['BBL_20_2.0']) / (df['BBU_20_2.0'] - df['BBL_20_2.0'])
    print("percent_b calc success")
except KeyError as e:
    print("percent_b calc failed:", e)

try:
    df['rvol'] = df['volume']/df['VOLUME_SMA_20']
    print("rvol calc success")
except KeyError as e:
    print("rvol calc failed:", e)
