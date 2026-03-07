"""
Stop-loss calculation utilities.

All configuration values come from ConfigModel - no hardcoding.
"""
from typing import Optional


def calculate_initial_stop_loss(
    buy_price: float,
    atr: Optional[float],
    stop_multiplier: float,
    config=None
) -> float:
    """
    Calculate initial ATR-based stop-loss at entry.

    Returns 0 if ATR is missing or zero — callers must treat this as
    "cannot size this trade" and skip the buy entirely.

    Parameters:
        buy_price (float): Entry price
        atr (float | None): Average True Range (14-period)
        stop_multiplier (float): ATR multiplier from config
        config: Unused; kept for backward-compatible signature

    Returns:
        float: Initial stop-loss price, or 0 if ATR unavailable
    """
    if atr is None or atr <= 0:
        return 0  # caller should skip this buy

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
    Calculate effective stop-loss using ATR trailing method.
    Delegates to calculate_atr_trailing_stop (monotone-up).

    Parameters:
        current_price (float): Current stock price
        current_atr (float): Current ATR value
        stop_multiplier (float): ATR multiplier
        previous_stop (float): Previous effective stop

    Returns:
        float: New effective stop-loss price
    """
    atr_stop = calculate_atr_trailing_stop(
        current_price, current_atr, stop_multiplier, previous_stop
    )
    return round(atr_stop, 2)
