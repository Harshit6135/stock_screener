
def calculate_initial_stop_loss(buy_price: float, atr: float, stop_multiplier) -> float:
    """
    Calculate initial ATR-based stop-loss at entry.

    Formula: stop = buy_price - (multiplier × ATR)
    """
    if atr is None or atr <= 0:
        return buy_price * 0.95

    stop_loss = buy_price - (stop_multiplier * atr)
    return max(stop_loss, 0)


def calculate_atr_trailing_stop(current_price: float, current_atr: float, stop_multiplier, previous_stop: float = 0, ) -> float:
    """
    Calculate ATR trailing stop based on current price and ATR.
    Only moves up, never down.
    """
    if current_atr is None or current_atr <= 0:
        return previous_stop

    new_stop = current_price - (stop_multiplier * current_atr)

    # Trail only upward
    return max(new_stop, previous_stop)


def calculate_trailing_hard_stop(buy_price: float, current_price: float, initial_stop: float, sl_step_percent) -> float:
    """
    Calculate trailing hard stop that moves up in 10% increments.

    Logic: For every 10% the stock gains, the stop moves up by 10%
    of the INITIAL stop value (not compounding).
    """
    if current_price <= buy_price:
        return initial_stop

    gain_percent = (current_price - buy_price) / buy_price
    tiers = int(gain_percent // sl_step_percent)  # How many complete 10% gains

    # Move stop up by 10% for each tier
    adjustment = 1 + (sl_step_percent * tiers)
    hard_stop = initial_stop * adjustment

    # Stop should never exceed entry price (that would lock in guaranteed profit)
    return min(hard_stop, buy_price)


def calculate_effective_stop(buy_price: float, current_price: float, current_atr: float, initial_stop: float,
                              stop_multiplier, sl_step_percent, previous_stop: float = 0) -> dict:
    """
    Calculate the effective stop-loss using both ATR and hard trailing methods.

    Returns the MIN of both (more breath).
    """
    atr_stop = calculate_atr_trailing_stop(current_price, current_atr, stop_multiplier, previous_stop)
    hard_stop = calculate_trailing_hard_stop(buy_price, current_price, initial_stop, sl_step_percent)

    effective_stop = min(atr_stop, hard_stop)

    return {
        "atr_stop": round(atr_stop, 2),
        "hard_stop": round(hard_stop, 2),
        "effective_stop": round(effective_stop, 2)
    }
