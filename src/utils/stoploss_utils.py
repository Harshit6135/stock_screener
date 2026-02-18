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

def calculate_effective_stop(
    current_price: float,
    current_atr: Optional[float], 
    stop_multiplier: float,
    previous_stop: float = 0
):
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
    return  round(atr_stop, 2)
