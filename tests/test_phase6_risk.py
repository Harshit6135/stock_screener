import pytest
from src.execution_gateway.risk_guard import (
    RiskGuardLimits,
    PortfolioRiskConfig,
    RiskGuardValidator,
    ProposedOrder,
)


def test_portfolio_risk_config(tmp_path):
    db_path = tmp_path / "system.db"
    config = PortfolioRiskConfig(db_path)
    
    version, limits = config.get_limits()
    assert version == 1
    assert limits.max_positions is None
    
    new_version = config.update_limits(RiskGuardLimits(max_positions=5, max_concentration=0.2))
    assert new_version == 2
    
    version, limits = config.get_limits()
    assert version == 2
    assert limits.max_positions == 5
    assert limits.max_concentration == 0.2


def test_risk_guard_validator():
    limits = RiskGuardLimits(
        max_positions=3,
        min_reserve_cash=1000,
        max_order_value=5000,
        max_concentration=0.5,
        max_heat=0.02
    )
    
    # Starting with 1 holding, cash 6000
    # Total equity = 6000 + 4000 = 10000
    holdings = {
        "inst1": {"units": 100, "value": 4000, "stop": 35} 
        # Risk = 4000 - (35*100) = 500. Heat = 500 / 10000 = 0.05 (Fails heat max 0.02, but this is pre-existing)
    }
    
    validator = RiskGuardValidator(limits, 6000, holdings, [])
    
    # 1. Order value exceeds 5000
    orders1 = [ProposedOrder("inst2", "BUY", 100, 60)] # 6000
    violations1 = validator.validate_orders(orders1)
    assert any("exceeds max 5000" in v for v in violations1)
    
    # 2. Reserve cash below 1000
    orders2 = [ProposedOrder("inst2", "BUY", 100, 55)] # 5500, cash will be 500 < 1000
    violations2 = validator.validate_orders(orders2)
    assert any("below minimum reserve 1000" in v for v in violations2)
    
    # 3. Max positions exceeded
    holdings3 = {
        "inst1": {"units": 100, "value": 1000},
        "inst2": {"units": 100, "value": 1000},
        "inst3": {"units": 100, "value": 1000},
    }
    validator3 = RiskGuardValidator(limits, 10000, holdings3, [])
    orders3 = [ProposedOrder("inst4", "BUY", 10, 10)]
    violations3 = validator3.validate_orders(orders3)
    assert any("Projected positions 4 exceeds max 3" in v for v in violations3)
    
    # 4. Heat exceeded
    limits4 = RiskGuardLimits(max_heat=0.02)
    holdings4 = {}
    validator4 = RiskGuardValidator(limits4, 10000, holdings4, [])
    
    # Buy 100 @ 50 = 5000 (Equity 10000). Stop at 40 -> Risk = 1000. Heat = 1000/10000 = 0.1 > 0.02
    orders4 = [ProposedOrder("inst4", "BUY", 100, 50, stop_price=40)]
    violations4 = validator4.validate_orders(orders4)
    assert any("Heat for inst4 (10.00%) exceeds max 2.00%" in v for v in violations4)
