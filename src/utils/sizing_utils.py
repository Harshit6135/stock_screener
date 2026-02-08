from config.strategies_config import PositionSizingConfig


def calculate_position_size(atr: float, current_price: float,
                             portfolio_value: float,
                             avg_daily_volume_value: float = None,
                             config: PositionSizingConfig = None) -> dict:
    """
    Calculate position size with multiple constraints
    
    Constraints applied (most restrictive wins):
    1. ATR risk parity: risk_per_trade_percent of portfolio per trade
    2. Liquidity: max_adv_percent of 20-day ADV × max_adv_days
    3. Concentration: concentration_limit of portfolio
    4. Minimum: skip if below min_position_percent
    
    Args:
        atr: Average True Range
        current_price: Current stock price
        portfolio_value: Total portfolio value
        avg_daily_volume_value: 20-day average daily turnover in INR
        config: PositionSizingConfig with constraints
        
    Returns:
        dict with shares, position_value, constraints applied
    """
    if config is None:
        config = PositionSizingConfig()
    
    if atr is None or atr <= 0 or current_price <= 0:
        return {
            "shares": 0,
            "position_value": 0,
            "stop_distance": 0,
            "error": "Invalid ATR or price",
            "constraint_applied": "error"
        }
    
    constraints = {}
    
    # 1. ATR risk parity
    risk_amount = portfolio_value * config.risk_per_trade_percent
    stop_distance = atr * config.stop_multiplier
    atr_shares = int(risk_amount / stop_distance)
    atr_position = atr_shares * current_price
    constraints['atr_risk'] = atr_position
    
    # 2. Liquidity constraint
    if avg_daily_volume_value and avg_daily_volume_value > 0:
        liquidity_limit = avg_daily_volume_value * config.max_adv_percent * config.max_adv_days
        constraints['liquidity'] = liquidity_limit
    else:
        constraints['liquidity'] = float('inf')
    
    # 3. Concentration limit
    concentration_limit = portfolio_value * config.concentration_limit
    constraints['concentration'] = concentration_limit
    
    # 4. Minimum position check
    min_position = portfolio_value * config.min_position_percent
    
    # Apply most restrictive constraint
    max_position_value = min(constraints.values())
    applied_constraint = min(constraints, key=constraints.get)
    
    shares = int(max_position_value / current_price)
    shares = max(1, shares)
    position_value = shares * current_price
    
    # Check minimum
    if position_value < min_position:
        return {
            "shares": 0,
            "position_value": 0,
            "stop_distance": round(stop_distance, 2),
            "error": f"Below minimum position {config.min_position_percent*100}%",
            "constraint_applied": "minimum"
        }
    
    return {
        "shares": shares,
        "position_value": round(position_value, 2),
        "stop_distance": round(stop_distance, 2),
        "risk_amount": round(shares * stop_distance, 2),
        "constraint_applied": applied_constraint,
        "constraints": {k: round(v, 2) for k, v in constraints.items() if v != float('inf')}
    }


def calculate_equal_weight_position(portfolio_value: float, max_positions: int,
                                     current_price: float) -> dict:
    """
    Simple equal-weight position sizing.
    
    Parameters:
        portfolio_value (float): Total portfolio value in INR
        max_positions (int): Maximum number of positions
        current_price (float): Current stock price
    
    Returns:
        dict: Position sizing with 'shares' and 'position_value'
    
    Raises:
        ValueError: If max_positions <= 0 or current_price <= 0
    
    Example:
        >>> result = calculate_equal_weight_position(100000, 10, 500)
        >>> result['shares']
        20
        >>> result['position_value']
        10000.0
    """
    if max_positions <= 0:
        raise ValueError(f"max_positions must be positive, got {max_positions}")
    if current_price <= 0:
        raise ValueError(f"current_price must be positive, got {current_price}")
    if portfolio_value <= 0:
        raise ValueError(f"portfolio_value must be positive, got {portfolio_value}")
    
    position_value = portfolio_value / max_positions
    shares = int(position_value / current_price)
    
    return {
        "shares": max(1, shares),
        "position_value": round(shares * current_price, 2)
    }

