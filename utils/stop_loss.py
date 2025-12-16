"""
Dual Stop-Loss System:
1. ATR Trailing Stop: Based on volatility, moves up with price
2. Hard Trailing Stop: Moves up 10% for every 10% stock gain

The effective stop is the MAX of both (protects more aggressively)
"""


def calculate_initial_stop_loss(buy_price: float, atr: float, multiplier: float = 2.0) -> float:
    """
    Calculate initial ATR-based stop-loss at entry.
    
    Formula: stop = buy_price - (multiplier × ATR)
    
    Args:
        buy_price: Entry price
        atr: Average True Range at entry
        multiplier: ATR multiplier (default 2.0)
    
    Returns:
        Initial stop-loss price
    """
    if atr is None or atr <= 0:
        # Fallback: 5% below buy price if ATR unavailable
        return buy_price * 0.95
    
    stop_loss = buy_price - (multiplier * atr)
    return max(stop_loss, 0)  # Can't be negative


def calculate_trailing_hard_stop(
    buy_price: float, 
    current_price: float, 
    initial_stop: float,
    step_percent: float = 0.10
) -> float:
    """
    Calculate trailing hard stop that moves up in 10% increments.
    
    Logic: For every 10% the stock gains, the stop moves up by 10%
    of the INITIAL stop value (not compounding).
    
    Args:
        buy_price: Original entry price
        current_price: Current market price
        initial_stop: Initial stop-loss at entry
        step_percent: Step size for moves (default 10%)
    
    Returns:
        New hard trailing stop price
    """
    if current_price <= buy_price:
        return initial_stop
    
    gain_percent = (current_price - buy_price) / buy_price
    tiers = int(gain_percent // step_percent)  # How many complete 10% gains
    
    # Move stop up by 10% for each tier
    adjustment = 1 + (step_percent * tiers)
    hard_stop = initial_stop * adjustment
    
    # Stop should never exceed entry price (that would lock in guaranteed profit)
    return min(hard_stop, buy_price)


def calculate_atr_trailing_stop(
    current_price: float,
    current_atr: float,
    multiplier: float = 2.0,
    previous_stop: float = 0
) -> float:
    """
    Calculate ATR trailing stop based on current price and ATR.
    Only moves up, never down.
    
    Args:
        current_price: Current market price
        current_atr: Current ATR value
        multiplier: ATR multiplier
        previous_stop: Previous stop level (never go below this)
    
    Returns:
        ATR trailing stop price
    """
    if current_atr is None or current_atr <= 0:
        return previous_stop
    
    new_stop = current_price - (multiplier * current_atr)
    
    # Trail only upward
    return max(new_stop, previous_stop)


def calculate_effective_stop(
    buy_price: float,
    current_price: float,
    current_atr: float,
    initial_stop: float,
    previous_stop: float = 0,
    multiplier: float = 2.0
) -> dict:
    """
    Calculate the effective stop-loss using both ATR and hard trailing methods.
    
    Returns the MAX of both (more protective).
    
    Args:
        buy_price: Original entry price
        current_price: Current market price  
        current_atr: Current ATR value
        initial_stop: Initial stop at entry
        previous_stop: Previous effective stop
        multiplier: ATR multiplier
    
    Returns:
        Dict with atr_stop, hard_stop, and effective_stop
    """
    atr_stop = calculate_atr_trailing_stop(
        current_price, current_atr, multiplier, previous_stop
    )
    
    hard_stop = calculate_trailing_hard_stop(
        buy_price, current_price, initial_stop
    )
    
    effective_stop = max(atr_stop, hard_stop)
    
    return {
        "atr_stop": round(atr_stop, 2),
        "hard_stop": round(hard_stop, 2),
        "effective_stop": round(effective_stop, 2)
    }


def should_trigger_stop_loss(current_price: float, effective_stop: float) -> bool:
    """
    Check if current price has breached the stop-loss level.
    
    Args:
        current_price: Current market price
        effective_stop: Current stop-loss level
    
    Returns:
        True if stop-loss triggered
    """
    return current_price <= effective_stop
