class Strategy1Parameters:
    """Configuration for factor weights in composite score"""
    trend_strength_weight: float = 0.30
    momentum_velocity_weight: float = 0.25
    risk_efficiency_weight: float = 0.20
    conviction_weight: float = 0.15
    structure_weight: float = 0.10
    trend_rank_weight: float = 0.6
    trend_extension_rank_weight: float = 0.4
    momentum_rsi_rank_weight: float = 0.5 #0.6
    momentum_ppo_rank_weight: float = 0.3 #0.25
    momentum_ppoh_rank_weight: float = 0.2 #0.15
    rvolume_rank_weight: float = 0.7
    price_vol_corr_rank_weight: float = 0.3
    structure_rank_weight: float = 0.5
    structure_bb_rank_weight: float = 0.5
    turnover_threshold: float = 1 # in CR
    atr_threshold: float = 2