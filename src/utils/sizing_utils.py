
def calculate_position_size(atr: float, current_price: float,
                             total_capital: float,
                             remaining_capital: float = None,
                             config=None,
                             existing_position_value: float = 0.0) -> dict:
    """
    Calculate position size with multiple constraints.

    Constraints applied (most restrictive wins):
    1. ATR risk parity: risk_threshold % of portfolio per trade
    2. Concentration cap: combined position (existing + new) ≤ 25% of total_capital
    3. Capital available: cannot exceed remaining_capital
    4. Minimum: skip if below min_position_percent

    Args:
        atr: Average True Range (must be > 0; returns 0 shares if missing)
        current_price: Current stock price
        total_capital: Total portfolio value (used for risk % and concentration cap)
        remaining_capital: Cash available to deploy
        config: Strategy config object (must be supplied by caller)
        existing_position_value: Current market value already held in this symbol
                                 (used to compute headroom under the 25% cap;
                                  pass 0 for new positions, actual value for pyramids)

    Returns:
        dict with shares, position_value, stop_distance, risk_amount
    """
    if not config:
        raise ValueError(
            "calculate_position_size: config must be provided. "
            "Pass the active strategy config explicitly."
        )

    # Guard: ATR must be positive — without it we can't size risk-parity
    if not atr or atr <= 0:
        return {"shares": 0, "position_value": 0, "stop_distance": 0, "risk_amount": 0}

    stop_distance = atr * config.sl_multiplier
    if stop_distance <= 0:
        return {"shares": 0, "position_value": 0, "stop_distance": 0, "risk_amount": 0}

    # 1. ATR risk-parity sizing
    risk_amount = total_capital * (config.risk_threshold / 100)
    shares = int(risk_amount / stop_distance)
    position_value = shares * current_price

    # 2. Remaining-capital cap
    if remaining_capital is not None and position_value > remaining_capital:
        position_value = remaining_capital
        shares = int(position_value / current_price)
        position_value = shares * current_price

    # 3. Concentration cap: existing + new ≤ 25% of total portfolio
    max_total_exposure = total_capital * 0.25
    headroom = max(0.0, max_total_exposure - existing_position_value)
    if position_value > headroom:
        position_value = headroom
        shares = int(position_value / current_price)
        position_value = shares * current_price

    # 4. Minimum position check
    if position_value < config.min_position_percent * total_capital:
        return {"shares": 0, "position_value": 0, "stop_distance": 0, "risk_amount": 0}

    return {
        "shares": shares,
        "position_value": round(position_value, 2),
        "stop_distance": round(stop_distance, 2),
        "risk_amount": round(shares * stop_distance, 2)
    }
