import pytest
import pandas_ta as ta
from config.indicators_config import momentum_strategy, derived_strategy, additional_parameters

def test_momentum_strategy_config():
    assert isinstance(momentum_strategy, ta.Study)
    assert momentum_strategy.name == "Momentum Strategy"
    # Check for core indicators
    kinds = [item['kind'] for item in momentum_strategy.ta]
    assert 'ema' in kinds
    assert 'rsi' in kinds
    assert 'roc' in kinds
    assert 'ppo' in kinds
    assert 'atr' in kinds

def test_derived_strategy_config():
    assert isinstance(derived_strategy, ta.Study)
    kinds = [item['kind'] for item in derived_strategy.ta]
    # Should calculate EMA of RSI
    assert 'ema' in kinds
    
def test_additional_params():
    assert 'vol_price_lookback' in additional_parameters
    assert 'ema_slope_lookback' in additional_parameters
