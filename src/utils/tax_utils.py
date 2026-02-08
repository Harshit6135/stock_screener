from datetime import date
from config.strategies_config import TaxConfig


def calculate_capital_gains_tax(purchase_price: float, current_price: float,
                                 purchase_date: date, current_date: date,
                                 quantity: int = 1,
                                 config: TaxConfig = None) -> dict:
    """
    Calculate capital gains tax for Indian equity
    
    STCG: < 12 months holding, taxed at 20%
    LTCG: >= 12 months holding, taxed at 12.5% above ₹1.25L exemption
    
    Args:
        purchase_price: Buy price per share
        current_price: Sell price per share
        purchase_date: Date of purchase
        current_date: Date of sale
        quantity: Number of shares
        config: TaxConfig with rates
        
    Returns:
        dict with gain, tax type, tax amount, and net proceeds
    """
    if config is None:
        config = TaxConfig()
    
    holding_days = (current_date - purchase_date).days
    gain_per_share = current_price - purchase_price
    total_gain = gain_per_share * quantity
    
    if total_gain <= 0:
        return {
            "gain": round(total_gain, 2),
            "holding_days": holding_days,
            "tax_type": "no_gain",
            "tax": 0,
            "net_gain": round(total_gain, 2)
        }
    
    if holding_days < config.ltcg_holding_days:
        # Short-term capital gains
        tax = total_gain * config.stcg_rate
        tax_type = "STCG"
    else:
        # Long-term capital gains
        taxable_gain = max(0, total_gain - config.ltcg_exemption)
        tax = taxable_gain * config.ltcg_rate
        tax_type = "LTCG"
    
    return {
        "gain": round(total_gain, 2),
        "holding_days": holding_days,
        "tax_type": tax_type,
        "tax": round(tax, 2),
        "net_gain": round(total_gain - tax, 2)
    }


def should_hold_for_ltcg(purchase_date: date, current_date: date,
                          current_score: float,
                          config: TaxConfig = None) -> dict:
    """
    Check if holding for LTCG is beneficial
    
    Returns:
        dict with recommendation and reasoning
    """
    if config is None:
        config = TaxConfig()
    
    holding_days = (current_date - purchase_date).days
    days_to_ltcg = config.ltcg_holding_days - holding_days
    
    # Already LTCG eligible
    if days_to_ltcg <= 0:
        return {
            "hold_for_ltcg": False,
            "reason": "already_ltcg",
            "days_to_ltcg": 0
        }
    
    # Not in tax hold window
    if holding_days < config.tax_hold_window_start:
        return {
            "hold_for_ltcg": False,
            "reason": "too_early",
            "days_to_ltcg": days_to_ltcg
        }
    
    # In window, check score
    if current_score >= config.tax_hold_min_score:
        return {
            "hold_for_ltcg": True,
            "reason": f"score>={config.tax_hold_min_score}_and_{days_to_ltcg}d_to_ltcg",
            "days_to_ltcg": days_to_ltcg
        }
    
    return {
        "hold_for_ltcg": False,
        "reason": f"score<{config.tax_hold_min_score}",
        "days_to_ltcg": days_to_ltcg
    }


def calculate_tax_adjusted_cost(purchase_price: float, current_price: float,
                                 purchase_date: date, current_date: date,
                                 quantity: int, switching_cost_pct: float,
                                 config: TaxConfig = None) -> float:
    """
    Calculate effective switching cost including tax impact
    
    Returns:
        Total switching cost percentage
    """
    if config is None:
        config = TaxConfig()
    
    tax_info = calculate_capital_gains_tax(
        purchase_price, current_price, purchase_date, current_date, quantity, config)
    
    trade_value = current_price * quantity
    tax_pct = tax_info['tax'] / trade_value if trade_value > 0 else 0
    
    return switching_cost_pct + tax_pct
