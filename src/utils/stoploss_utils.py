"""
Stop-loss calculation utilities.

All configuration values come from ConfigModel - no hardcoding.
"""
from typing import Optional


def calculate_initial_stop_loss(
    buy_price: float, 
    atr: Optional[float], 
    stop_multiplier: float,
    config = None
) -> float:
    """
    Calculate initial ATR-based stop-loss at entry.

    Parameters:
        buy_price (float): Entry price
        atr (float): Average True Range (14-period)
        stop_multiplier (float): ATR multiplier from config
        config: Config object with sl_fallback_percent

    Returns:
        float: Initial stop-loss price

    Example:
        >>> calculate_initial_stop_loss(100.0, 5.0, 2.0)
        90.0
    """
    if config is None or not hasattr(config, 'sl_fallback_percent'):
        sl_fallback = 0.06  # default 6%
    else:
        sl_fallback = config.sl_fallback_percent
    
    if atr is None or atr <= 0:
        return buy_price * (1 - sl_fallback)

    stop_loss = buy_price - (stop_multiplier * atr)
    return max(stop_loss, 0)


def calculate_atr_trailing_stop(
    current_price: float, 
    current_atr: Optional[float], 
    stop_multiplier: float, 
    previous_stop: float = 0
) -> float:
    """
    Calculate ATR trailing stop based on current price and ATR.
    Only moves up, never down (protects profits).

    Parameters:
        current_price (float): Current stock price
        current_atr (float): Current ATR value
        stop_multiplier (float): ATR multiplier
        previous_stop (float): Previous stop-loss level

    Returns:
        float: New stop-loss (max of calculated and previous)
    """
    if current_atr is None or current_atr <= 0:
        return previous_stop

    new_stop = current_price - (stop_multiplier * current_atr)

    # Trail only upward
    return max(new_stop, previous_stop)


def calculate_trailing_hard_stop(
    buy_price: float, 
    current_price: float, 
    initial_stop: float, 
    sl_step_percent: float
) -> float:
    """
    Calculate trailing hard stop that moves up in increments.

    Logic: For every sl_step_percent the stock gains, the stop moves up
    by the same percentage of the INITIAL stop value.

    Parameters:
        buy_price (float): Original entry price
        current_price (float): Current stock price
        initial_stop (float): Initial stop-loss at entry
        sl_step_percent (float): Step increment (e.g., 0.10 for 10%)

    Returns:
        float: Hard stop-loss level
    """
    if current_price <= buy_price:
        return initial_stop

    gain_percent = (current_price - buy_price) / buy_price
    tiers = int(gain_percent // sl_step_percent)

    # Move stop up for each tier
    adjustment = 1 + (sl_step_percent * tiers)
    hard_stop = initial_stop * adjustment

    # Stop should never exceed entry price
    return min(hard_stop, buy_price)


def calculate_effective_stop(
    buy_price: float, 
    current_price: float, 
    current_atr: Optional[float], 
    initial_stop: float,
    stop_multiplier: float, 
    sl_step_percent: float, 
    previous_stop: float = 0
) -> dict:
    """
    Calculate effective stop-loss using both ATR and hard trailing methods.

    Returns MIN of both methods (more breathing room).

    Parameters:
        buy_price (float): Original entry price
        current_price (float): Current stock price
        current_atr (float): Current ATR value
        initial_stop (float): Initial stop at entry
        stop_multiplier (float): ATR multiplier
        sl_step_percent (float): Hard trailing step
        previous_stop (float): Previous effective stop

    Returns:
        dict: {atr_stop, hard_stop, effective_stop}
    """
    atr_stop = calculate_atr_trailing_stop(
        current_price, current_atr, stop_multiplier, previous_stop
    )
    hard_stop = calculate_trailing_hard_stop(
        buy_price, current_price, initial_stop, sl_step_percent
    )

    effective_stop = min(atr_stop, hard_stop)

    return {
        "atr_stop": round(atr_stop, 2),
        "hard_stop": round(hard_stop, 2),
        "effective_stop": round(effective_stop, 2)
    }
