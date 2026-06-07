from datetime import date
from typing import Dict, List

from config import TaxConfig


def calculate_capital_gains_tax(
    purchase_price: float,
    current_price: float,
    purchase_date: date,
    current_date: date,
    quantity: int = 1,
    config: TaxConfig = None,
) -> dict:
    """
    Calculate capital gains tax for Indian equity (per-trade estimation).

    NOTE (R-11): This computes tax for a single trade. It does NOT net
    gains/losses across the financial year. For accurate FY-level netting,
    use compute_trade_costs_and_taxes() which aggregates by FY.
    Per-action tax from this function is an upper-bound estimate.

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

    if holding_days < config.ltcg_holding_days:
        # Short-term capital gains/losses
        tax = max(0.0, float(total_gain) * config.stcg_rate)
        tax_type = "STCG"
    else:
        # Long-term capital gains/losses
        taxable_gain = max(0.0, float(total_gain) - config.ltcg_exemption)
        tax = taxable_gain * config.ltcg_rate
        tax_type = "LTCG"

    return {
        "gain": round(total_gain, 2),
        "holding_days": holding_days,
        "tax_type": tax_type,
        "tax": round(tax, 2),
        "net_gain": round(total_gain - tax, 2),
    }


def should_hold_for_ltcg(
    purchase_date: date, current_date: date, current_score: float, config: TaxConfig = None
) -> dict:
    """
    Check if holding for LTCG is beneficial.

    Recommends holding if:
    - In tax hold window (300-365 days)
    - Score >= minimum threshold

    Parameters:
        purchase_date: Date of purchase
        current_date: Current date
        current_score: Current composite score
        config: TaxConfig with rates

    Returns:
        dict with hold_for_ltcg (bool), reason (str), days_to_ltcg (int)
    """
    if config is None:
        config = TaxConfig()

    holding_days = (current_date - purchase_date).days
    days_to_ltcg = config.ltcg_holding_days - holding_days

    # Already LTCG eligible
    if days_to_ltcg <= 0:
        return {"hold_for_ltcg": False, "reason": "already_ltcg", "days_to_ltcg": 0}

    # Not in tax hold window
    if holding_days < config.tax_hold_window_start:
        return {"hold_for_ltcg": False, "reason": "too_early", "days_to_ltcg": days_to_ltcg}

    # In window, check score
    if current_score >= config.tax_hold_min_score:
        return {
            "hold_for_ltcg": True,
            "reason": f"score>={config.tax_hold_min_score}_and_{days_to_ltcg}d_to_ltcg",
            "days_to_ltcg": days_to_ltcg,
        }

    return {
        "hold_for_ltcg": False,
        "reason": f"score<{config.tax_hold_min_score}",
        "days_to_ltcg": days_to_ltcg,
    }


def calculate_tax_adjusted_cost(
    purchase_price: float,
    current_price: float,
    purchase_date: date,
    current_date: date,
    quantity: int,
    switching_cost_pct: float,
    config: TaxConfig = None,
) -> float:
    """
    Calculate effective switching cost including tax impact.

    Useful for swap decisions where tax must be considered.

    Parameters:
        purchase_price: Buy price per share
        current_price: Current/sell price per share
        purchase_date: Date of purchase
        current_date: Date of sale
        quantity: Number of shares
        switching_cost_pct: Transaction cost percentage (from costs utils)
        config: TaxConfig with rates

    Returns:
        float: Total switching cost percentage (transaction + tax)
    """
    if config is None:
        config = TaxConfig()

    tax_info = calculate_capital_gains_tax(
        purchase_price, current_price, purchase_date, current_date, quantity, config
    )

    trade_value = current_price * quantity
    tax_pct = tax_info["tax"] / trade_value if trade_value > 0 else 0

    return round(switching_cost_pct + tax_pct, 4)


def compute_trade_costs_and_taxes(sell_trades: List[Dict], config: TaxConfig = None) -> Dict:
    """
    Compute transaction costs and capital gains tax from a list of completed sell trades.

    Uses FY-level netting for capital gains (losses offset gains within the same
    Indian financial year), which gives a more accurate tax estimate than the
    per-trade ``calculate_capital_gains_tax`` helper.

    This is the canonical implementation shared by the backtest report builder
    and any future live-trading tax summary. Both STCG and LTCG are bucketed by
    FY so that loss years correctly reduce taxable gains.

    Parameters:
        sell_trades: List of trade dicts, each with keys:
            price       - buy (entry) price per share
            exit_price  - sell price per share
            units       - number of shares
            entry_date  - date of purchase (date object)
            exit_date   - date of sale (date object)
            pnl         - realised PnL (exit_value - entry_value)
        config: TaxConfig (defaults to TaxConfig())

    Returns:
        dict with full cost and tax breakdown:
            total_buy_cost, total_sell_cost, total_transaction_costs,
            total_brokerage, total_stt, total_gst, total_stamp,
            total_buy_value, total_sell_value,
            total_tax, stcg_tax, ltcg_tax,
            stcg_gains, ltcg_gains, stcg_count, ltcg_count
    """
    from utils.transaction_costs_utils import calculate_transaction_costs

    if config is None:
        config = TaxConfig()

    total_buy_cost = 0.0
    total_sell_cost = 0.0
    total_stt = 0.0
    total_gst = 0.0
    total_stamp = 0.0
    total_brokerage = 0.0
    total_buy_value = 0.0
    total_sell_value = 0.0

    for t in sell_trades:
        buy_value = t.get("price", 0) * t.get("units", 0)
        sell_value = t.get("exit_price", 0) * t.get("units", 0)
        total_buy_value += buy_value
        total_sell_value += sell_value

        bc = calculate_transaction_costs(buy_value, "buy")
        sc = calculate_transaction_costs(sell_value, "sell")
        total_buy_cost += bc["total"]
        total_sell_cost += sc["total"]
        total_stt += bc["stt"] + sc["stt"]
        total_gst += bc["gst"] + sc["gst"]
        total_stamp += bc["stamp"] + sc["stamp"]
        total_brokerage += bc["brokerage"] + sc["brokerage"]

    total_costs = total_buy_cost + total_sell_cost

    # FY-bucketed capital gains (losses offset gains within the same FY)
    stcg_by_year: Dict[int, float] = {}
    ltcg_by_year: Dict[int, float] = {}
    stcg_gains = 0.0
    ltcg_gains = 0.0
    stcg_count = 0
    ltcg_count = 0

    for t in sell_trades:
        tax_info = calculate_capital_gains_tax(
            purchase_price=t.get("price", 0),
            current_price=t.get("exit_price", 0),
            purchase_date=t.get("entry_date"),
            current_date=t["exit_date"],
            quantity=t.get("units", 0),
            config=config,
        )
        pnl = t.get("pnl", 0)
        exit_d = t["exit_date"]
        fy = exit_d.year if exit_d.month >= 4 else exit_d.year - 1

        if tax_info["tax_type"] == "STCG":
            stcg_gains += pnl
            stcg_count += 1
            stcg_by_year[fy] = stcg_by_year.get(fy, 0.0) + pnl
        elif tax_info["tax_type"] == "LTCG":
            ltcg_gains += pnl
            ltcg_count += 1
            ltcg_by_year[fy] = ltcg_by_year.get(fy, 0.0) + pnl

    stcg_total = sum(max(0.0, gain) * config.stcg_rate for gain in stcg_by_year.values())
    ltcg_total = sum(
        max(0.0, gain - config.ltcg_exemption) * config.ltcg_rate
        for gain in ltcg_by_year.values()
    )
    total_tax = stcg_total + ltcg_total

    return {
        "total_buy_cost": round(total_buy_cost, 2),
        "total_sell_cost": round(total_sell_cost, 2),
        "total_transaction_costs": round(total_costs, 2),
        "total_brokerage": round(total_brokerage, 2),
        "total_stt": round(total_stt, 2),
        "total_gst": round(total_gst, 2),
        "total_stamp": round(total_stamp, 2),
        "total_buy_value": round(total_buy_value, 2),
        "total_sell_value": round(total_sell_value, 2),
        "total_tax": round(total_tax, 2),
        "stcg_tax": round(stcg_total, 2),
        "ltcg_tax": round(ltcg_total, 2),
        "stcg_gains": round(stcg_gains, 2),
        "ltcg_gains": round(ltcg_gains, 2),
        "stcg_count": stcg_count,
        "ltcg_count": ltcg_count,
    }
