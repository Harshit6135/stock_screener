class TaxConfig:
    """Capital gains tax parameters (India)"""
    stcg_rate: float = 0.20  # 20% for < 12 months
    ltcg_rate: float = 0.125  # 12.5% for >= 12 months
    ltcg_exemption: float = 125000  # ₹1.25L per year
    ltcg_holding_days: int = 365
    tax_hold_window_start: int = 300  # bias hold if 300-365 days
    tax_hold_min_score: float = 50
