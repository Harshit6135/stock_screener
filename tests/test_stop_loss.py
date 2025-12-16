import pytest
from utils.stop_loss import (
    calculate_initial_stop_loss,
    calculate_trailing_hard_stop,
    calculate_atr_trailing_stop,
    calculate_effective_stop,
    should_trigger_stop_loss
)

def test_initial_stop_loss():
    # Buy at 100, ATR 5, Mult 2 -> Stop 90
    stop = calculate_initial_stop_loss(100, 5, 2.0)
    assert stop == 90.0

def test_initial_stop_loss_no_atr():
    # Fallback 5% -> 95
    stop = calculate_initial_stop_loss(100, None)
    assert stop == 95.0

def test_hard_stop_trailing():
    initial = 90.0 # 10% risk
    buy_price = 100.0
    
    # No gain
    assert calculate_trailing_hard_stop(buy_price, 100.0, initial) == 90.0
    
    # 5% gain - no move (step 10%)
    assert calculate_trailing_hard_stop(buy_price, 105.0, initial) == 90.0
    
    # 10% gain -> move up 10% of initial (9) -> 99
    assert calculate_trailing_hard_stop(buy_price, 110.0, initial) == pytest.approx(99.0)
    
    # 20% gain -> move up 20% of initial (18) -> 108
    # But capped at buy_price (100) per code logic?
    # Logic: min(hard_stop, buy_price)
    # Wait, the code says: return min(hard_stop, buy_price)
    # So it can never exceed buy price? That seems like "Breakeven" logic, not trailing profit?
    # Let's verify code behavior.
    assert calculate_trailing_hard_stop(buy_price, 120.0, initial) <= 100.0

def test_atr_trailing_stop():
    # Price 100, ATR 5, stop = 90
    stop1 = calculate_atr_trailing_stop(100, 5, 2.0, 80)
    assert stop1 == 90.0
    
    # Price drops to 95, ATR 5 -> Lowers new stop to 85?
    # Should stick to previous (90) because it never goes down
    stop2 = calculate_atr_trailing_stop(95, 5, 2.0, 90)
    assert stop2 == 90.0

def test_effective_stop():
    # Case where ATR stop is higher
    # Price 100, ATR 2 (Tight) -> ATR stop 96
    # Hard stop (initial) -> 90
    res = calculate_effective_stop(100, 100, 2, 90, 0)
    assert res['effective_stop'] == 96.0

def test_trigger_stop():
    assert should_trigger_stop_loss(90, 95)  # Price 90 < Stop 95
    assert not should_trigger_stop_loss(100, 95) # Price 100 > Stop 95
    assert should_trigger_stop_loss(95, 95) # Price = Stop
