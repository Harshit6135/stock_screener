class TransactionCostConfig:
    """
    Indian market transaction cost parameters.
    
    Per NSE/BSE regulations:
    - STT: Buy and sell for delivery trades
    - Exchange: Buy and sell
    - SEBI: Buy and sell
    - Stamp Duty: Buy only
    - GST: Buy and sell (on brokerage + exchange + SEBI)
    - IPF: Buy and sell (Investor Protection Fund)
    - DP Charges: Sell only (Depository Participant charges)
    """
    brokerage_percent: float = 0.0
    brokerage_cap: float = 0.0
    stt_buy_percent: float = 0.001  # 0.1% on buy (delivery)
    stt_sell_percent: float = 0.001  # 0.1% on sell (delivery)
    exchange_percent: float = 0.0000345  # ~0.00345% on buy+sell
    sebi_per_crore: float = 10.0  # ₹10 per crore on buy+sell
    stamp_duty_percent: float = 0.00015  # 0.015% buy only
    gst_percent: float = 0.18  # 18% on taxable (buy+sell)
    ipf_per_crore: float = 10.0  # ₹10 per crore on buy+sell
    dp_charges: float = 13.0  # ₹13 per sell transaction


class ImpactCostConfig:
    """Impact cost tiers based on order size vs ADV"""
    tier1_threshold: float = 0.05  # < 5% ADV
    tier1_bps: float = 15
    tier2_threshold: float = 0.10  # < 10% ADV
    tier2_bps: float = 35
    tier3_threshold: float = 0.15  # < 15% ADV
    tier3_bps: float = 60
    tier4_bps: float = 150  # >= 15% ADV
