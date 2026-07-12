"""
Stop-loss calculation utilities.

Provides ATR-based trailing stop calculation shared between
InvestmentService (live trading) and ActionProcessor (backtesting).
"""

from typing import Optional


def calculate_atr_trailing_stop(
    current_price: float,
    current_atr: Optional[float],
    stop_multiplier: float,
    previous_stop: float = 0,
    round_digits: int = 2,
) -> float:
    """
    Calculate ATR trailing stop based on current price and ATR.
    Only moves up, never down (protects profits).

    Parameters:
        current_price (float): Current stock price
        current_atr (float): Current ATR value
        stop_multiplier (float): ATR multiplier
        previous_stop (float): Previous stop-loss level
        round_digits (int): Decimal places to round to (default 2)

    Returns:
        float: New stop-loss (max of calculated and previous)
    """
    if current_atr is None or current_atr <= 0:
        return previous_stop

    new_stop = current_price - (stop_multiplier * current_atr)

    # Trail only upward
    return round(max(new_stop, previous_stop), round_digits)


# Backward-compatible alias
calculate_effective_stop = calculate_atr_trailing_stop
