"""
ATR-Based Position Sizing (Volatility Sizing)

Ensures equal risk per position regardless of stock volatility.
Formula: Shares = Risk_Amount / (ATR × Stop_Multiplier)
"""


def calculate_position_size(
    risk_per_trade: float,
    atr: float,
    stop_multiplier: float = 2.0,
    current_price: float = None,
    max_position_value: float = None
) -> dict:
    """
    Calculate position size based on ATR and risk tolerance.
    
    Risk-adjusted sizing ensures that a high-volatility stock gets fewer
    shares than a low-volatility stock, equalizing portfolio risk.
    
    Args:
        risk_per_trade: Maximum loss per trade in ₹ (e.g., 1000)
        atr: Average True Range of the stock
        stop_multiplier: How many ATRs for stop-loss (default 2.0)
        current_price: Current stock price (for position value check)
        max_position_value: Maximum allowed position value (optional)
    
    Returns:
        Dict with shares, position_value, and stop_distance
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
    
    # Calculate shares based on risk
    shares = int(risk_per_trade / stop_distance)
    shares = max(1, shares)  # At least 1 share
    
    # Calculate position value
    position_value = shares * current_price if current_price else 0
    
    # Cap by max position value if specified
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


def calculate_capital_allocation(
    total_capital: float,
    num_positions: int,
    risk_per_trade: float,
    stocks: list
) -> list:
    """
    Allocate capital across multiple stocks based on their volatility.
    
    Args:
        total_capital: Total available capital
        num_positions: Target number of positions
        risk_per_trade: Risk per position
        stocks: List of dicts with 'symbol', 'price', 'atr'
    
    Returns:
        List of allocations with shares and position values
    """
    allocations = []
    remaining_capital = total_capital
    
    for stock in stocks[:num_positions]:
        if remaining_capital <= 0:
            break
            
        sizing = calculate_position_size(
            risk_per_trade=risk_per_trade,
            atr=stock.get('atr', 0),
            current_price=stock.get('price', 0),
            max_position_value=remaining_capital
        )
        
        if sizing['shares'] > 0:
            allocation = {
                'symbol': stock['symbol'],
                'shares': sizing['shares'],
                'price': stock.get('price', 0),
                'position_value': sizing['position_value'],
                'risk_amount': sizing['risk_amount']
            }
            allocations.append(allocation)
            remaining_capital -= sizing['position_value']
    
    return allocations


def rebalance_on_sale(
    current_capital: float,
    sale_proceeds: float,
    gain_loss: float
) -> dict:
    """
    Update capital after selling a position.
    
    Args:
        current_capital: Current available capital
        sale_proceeds: Proceeds from sale (shares × sale_price)
        gain_loss: Profit or loss from the trade
    
    Returns:
        Dict with new capital and stats
    """
    new_capital = current_capital + sale_proceeds
    
    return {
        "previous_capital": round(current_capital, 2),
        "sale_proceeds": round(sale_proceeds, 2),
        "gain_loss": round(gain_loss, 2),
        "new_capital": round(new_capital, 2)
    }
