"""
Position Sizing Utilities
=========================

Provides ATR-based, risk-parity position sizing with multiple safety constraints.

Algorithm overview
------------------
Given a target stock's ATR (Average True Range) and the portfolio config, the
sizing function computes how many shares to buy such that if the stock drops
to its stop-loss level (``current_price - ATR * sl_multiplier``), the loss
equals exactly ``total_capital * risk_threshold``.

This is the standard "risk-per-trade" sizing approach used in systematic
trend-following systems.

Four constraints applied in order
----------------------------------
1. **ATR risk-parity sizing** — ``units = (capital * risk%) / stop_distance``
2. **Remaining-capital spending limit** — cannot spend more cash than available
3. **Concentration cap** — no single position exceeds ``max_concentration_pct``
   of total capital (including any existing pyramid position in the same stock)
4. **Minimum position check** — if the final position is smaller than
   ``min_position_percent * total_capital``, return 0 units (reject the trade)

The function returns 0 units (not an error) when any hard constraint cannot
be satisfied, allowing callers to handle capital-constrained states gracefully.
"""

def calculate_position_size(
    atr: float,
    current_price: float,
    total_capital: float,
    remaining_capital: float = None,
    config=None,
    existing_position_value: float = 0.0,
) -> dict:
    """
    Calculate position size with multiple constraints.

    All constraints (concentration cap, minimum position) are evaluated
    against total_capital.  remaining_capital is only a spending limit —
    you cannot buy more than you have in cash.

    Order:
    1. ATR risk parity sizing (based on total_capital)
    2. Remaining-capital spending limit
    3. Concentration cap (based on total_capital)
    4. Minimum position check (based on total_capital, AFTER all caps)
       → if the final capped position is below the minimum, return 0

    Args:
        atr: Average True Range (must be > 0)
        current_price: Current stock price
        total_capital: Total portfolio value — used for ALL constraints
        remaining_capital: Cash available (spending limit only)
        config: Strategy config object
        existing_position_value: Market value already held in this symbol

    Returns:
        dict with shares, position_value, stop_distance, risk_amount
    """
    if not config:
        raise ValueError(
            "calculate_position_size: config must be provided. "
            "Pass the active strategy config explicitly."
        )

    ZERO = {"shares": 0, "position_value": 0, "stop_distance": 0, "risk_amount": 0}

    if not atr or atr <= 0:
        return ZERO

    stop_distance = atr * config.sl_multiplier
    if stop_distance <= 0:
        return ZERO

    # 1. ATR risk-parity sizing (based on total_capital)
    risk_amount = total_capital * (config.risk_threshold / 100)
    shares = int(risk_amount / stop_distance)
    position_value = shares * current_price

    # 2. Remaining-capital spending limit (can't buy more than you have)
    if remaining_capital is not None and position_value > remaining_capital:
        position_value = remaining_capital
        shares = int(position_value / current_price)
        position_value = shares * current_price

    # 3. Concentration cap (based on total_capital)
    concentration_limit = getattr(config, "max_concentration_pct", 0.25)
    max_total_exposure = total_capital * concentration_limit
    headroom = max(0.0, max_total_exposure - existing_position_value)
    if position_value > headroom:
        position_value = headroom
        shares = int(position_value / current_price)
        position_value = shares * current_price

    # 4. Minimum position check (based on total_capital, AFTER all caps)
    #    If the final position is too small relative to the portfolio, reject it.
    min_position_value = config.min_position_percent * total_capital
    if shares <= 0 or position_value < min_position_value:
        return ZERO

    return {
        "shares": shares,
        "position_value": round(position_value, 2),
        "stop_distance": round(stop_distance, 2),
        "risk_amount": round(shares * stop_distance, 2),
    }
