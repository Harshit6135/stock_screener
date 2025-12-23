def calculate_position_size(atr: float, stop_multiplier,
                            risk_per_trade, current_price: float = None, max_position_value: float = None) -> dict:
    """
    Calculate position size based on ATR and risk tolerance.

    Risk-adjusted sizing ensures that a high-volatility stock gets fewer
    shares than a low-volatility stock, equalizing portfolio risk.
    """
    if atr is None or atr <= 0:
        return {
            "shares": 0,
            "position_value": 0,
            "stop_distance": 0,
            "error": "Invalid ATR value"
        }

    # Calculate stop distance
    stop_distance = atr * stop_multiplier

    shares = int(risk_per_trade / stop_distance)
    shares = max(1, shares)

    # Calculate position value
    position_value = shares * current_price if current_price else 0

    if max_position_value and current_price and position_value > max_position_value:
        shares = int(max_position_value / current_price)
        shares = max(1, shares)
        position_value = shares * current_price

    return {
        "shares": shares,
        "position_value": round(position_value, 2),
        "stop_distance": round(stop_distance, 2),
        "risk_amount": round(shares * stop_distance, 2)
    }
