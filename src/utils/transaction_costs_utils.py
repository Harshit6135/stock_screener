from config.strategies_config import TransactionCostConfig, ImpactCostConfig


def calculate_transaction_costs(trade_value: float, side: str,
                                  config: TransactionCostConfig = None) -> dict:
    """
    Calculate Indian market transaction costs.
    
    Parameters:
        trade_value (float): Order value in INR
        side (str): 'buy' or 'sell'
        config (TransactionCostConfig): Cost configuration
        
    Returns:
        dict: Breakdown with brokerage, stt, exchange, sebi, stamp, gst, ipf, dp, total, percent
    """
    if config is None:
        config = TransactionCostConfig()
    
    # Brokerage: min of percentage or cap
    brokerage = min(trade_value * config.brokerage_percent, config.brokerage_cap)
    
    # STT: buy and sell for delivery trades
    if side == 'buy':
        stt = trade_value * config.stt_buy_percent
    else:
        stt = trade_value * config.stt_sell_percent
    
    # Exchange charges (buy and sell)
    exchange = trade_value * config.exchange_percent
    
    # SEBI charges (buy and sell)
    sebi = trade_value * config.sebi_per_crore / 1e7
    
    # Stamp duty: buy side only
    stamp = trade_value * config.stamp_duty_percent if side == 'buy' else 0
    
    # IPF charges (buy and sell)
    ipf = trade_value * config.ipf_per_crore / 1e7
    
    # DP charges: sell side only
    dp = config.dp_charges if side == 'sell' else 0
    
    # GST: on brokerage + exchange + SEBI (buy and sell)
    taxable = brokerage + exchange + sebi
    gst = taxable * config.gst_percent
    
    total = brokerage + stt + exchange + sebi + stamp + gst + ipf + dp
    
    return {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange": round(exchange, 2),
        "sebi": round(sebi, 2),
        "stamp": round(stamp, 2),
        "gst": round(gst, 2),
        "ipf": round(ipf, 2),
        "dp": round(dp, 2),
        "total": round(total, 2),
        "percent": round(total / trade_value * 100, 4) if trade_value > 0 else 0
    }


def calculate_buy_costs(trade_value: float,
                        config: TransactionCostConfig = None) -> dict:
    """
    Calculate buy-side transaction costs.
    
    Parameters:
        trade_value (float): Order value in INR
        config (TransactionCostConfig): Cost configuration
        
    Returns:
        dict: Breakdown with brokerage, stt, exchange, sebi, stamp, gst, total, percent
        
    Example:
        >>> costs = calculate_buy_costs(100000.0)
        >>> costs['total']
        15.35
    """
    return calculate_transaction_costs(trade_value, 'buy', config)


def calculate_sell_costs(trade_value: float,
                         config: TransactionCostConfig = None) -> dict:
    """
    Calculate sell-side transaction costs.
    
    Parameters:
        trade_value (float): Order value in INR
        config (TransactionCostConfig): Cost configuration
        
    Returns:
        dict: Breakdown with brokerage, stt, exchange, sebi, stamp, gst, total, percent
        
    Example:
        >>> costs = calculate_sell_costs(100000.0)
        >>> costs['total']
        118.06
    """
    return calculate_transaction_costs(trade_value, 'sell', config)


def calculate_impact_cost(order_pct_adv: float,
                          config: ImpactCostConfig = None) -> float:
    """
    Calculate market impact cost based on order size vs ADV
    
    Args:
        order_pct_adv: Order value as percentage of 20-day ADV (e.g., 0.05 = 5%)
        config: ImpactCostConfig with tier thresholds
        
    Returns:
        Impact cost as a decimal (e.g., 0.15 for 15 bps)
    """
    if config is None:
        config = ImpactCostConfig()
    
    if order_pct_adv < config.tier1_threshold:
        return config.tier1_bps / 10000
    elif order_pct_adv < config.tier2_threshold:
        return config.tier2_bps / 10000
    elif order_pct_adv < config.tier3_threshold:
        return config.tier3_bps / 10000
    else:
        return config.tier4_bps / 10000


def calculate_round_trip_cost(trade_value: float, order_pct_adv: float = 0.05,
                               tx_config: TransactionCostConfig = None,
                               impact_config: ImpactCostConfig = None) -> dict:
    """
    Calculate total round-trip cost (buy + sell + impact)
    
    Returns:
        dict with buy, sell, impact, and total costs
    """
    buy_costs = calculate_transaction_costs(trade_value, 'buy', tx_config)
    sell_costs = calculate_transaction_costs(trade_value, 'sell', tx_config)
    
    impact_buy = trade_value * calculate_impact_cost(order_pct_adv, impact_config)
    impact_sell = impact_buy  # assume symmetric
    
    total = buy_costs['total'] + sell_costs['total'] + impact_buy + impact_sell
    
    return {
        "buy_costs": buy_costs['total'],
        "sell_costs": sell_costs['total'],
        "impact_cost": round(impact_buy + impact_sell, 2),
        "total": round(total, 2),
        "percent": round(total / trade_value * 100, 4) if trade_value > 0 else 0
    }

