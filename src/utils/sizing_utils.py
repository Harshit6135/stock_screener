from repositories import ConfigRepository


config_repository = ConfigRepository()


def calculate_position_size(atr: float, current_price: float,
                             total_capital: float,
                             remaining_capital: float = None,
                             config = None) -> dict:
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

    Returns:
        dict with shares, position_value, constraints applied
    """
    if not config:
        config = config_repository.get_config('momentum_config')

    risk_amount = total_capital * (config.risk_threshold / 100)
    stop_distance = atr * config.sl_multiplier
    shares = int(risk_amount / stop_distance)
    
    position_value = shares * current_price
    if position_value > remaining_capital:
        position_value = remaining_capital
        shares = int(position_value / current_price)
    
    return {
        "shares": shares,
        "position_value": round(position_value, 2),
        "stop_distance": round(stop_distance, 2),
        "risk_amount": round(shares * stop_distance, 2)
    }
