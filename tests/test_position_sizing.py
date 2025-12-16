import pytest
from utils.position_sizing import calculate_position_size, calculate_capital_allocation, rebalance_on_sale

def test_calculate_position_size_valid():
    # Risk 1000, ATR 10, Multiplier 2 -> Stop dist 20 -> Shares 1000/20 = 50
    result = calculate_position_size(
        risk_per_trade=1000,
        atr=10.0,
        stop_multiplier=2.0,
        current_price=100.0
    )
    
    assert result['shares'] == 50
    assert result['stop_distance'] == 20.0
    assert result['position_value'] == 5000.0
    assert result['risk_amount'] == 1000.0

def test_calculate_position_size_invalid_atr():
    result = calculate_position_size(1000, 0)
    assert result['shares'] == 0
    assert 'error' in result

def test_calculate_position_size_max_value_cap():
    # Normal calc: 50 shares * 100 = 5000
    # Cap at 4000 -> shares should reduce to 40
    result = calculate_position_size(
        risk_per_trade=1000,
        atr=10.0,
        current_price=100.0,
        max_position_value=4000.0
    )
    
    assert result['shares'] == 40
    assert result['position_value'] == 4000.0

def test_calculate_capital_allocation():
    stocks = [
        {'symbol': 'A', 'price': 100, 'atr': 5},
        {'symbol': 'B', 'price': 200, 'atr': 10}
    ]
    
    allocations = calculate_capital_allocation(
        total_capital=100000,
        num_positions=5,
        risk_per_trade=1000,
        stocks=stocks
    )
    
    assert len(allocations) == 2
    # Stock A: Stop=10, Shares=1000/10=100, Val=10000
    assert allocations[0]['symbol'] == 'A'
    assert allocations[0]['shares'] == 100
    
    # Stock B: Stop=20, Shares=1000/20=50, Val=10000
    assert allocations[1]['symbol'] == 'B'
    assert allocations[1]['shares'] == 50

def test_rebalance_on_sale():
    result = rebalance_on_sale(
        current_capital=10000,
        sale_proceeds=5000,
        gain_loss=500
    )
    
    assert result['previous_capital'] == 10000
    assert result['sale_proceeds'] == 5000
    assert result['new_capital'] == 15000
    assert result['gain_loss'] == 500
