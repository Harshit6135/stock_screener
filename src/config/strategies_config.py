class StrategyParameters:
    """Configuration for factor weights in composite score"""
    trend_strength_weight: float = 0.30
    momentum_velocity_weight: float = 0.25
    risk_efficiency_weight: float = 0.20
    conviction_weight: float = 0.15
    structure_weight: float = 0.10
    
    # ATR spike threshold for penalty box (ratio of current ATR / lagged ATR)
    atr_threshold: float = 2.0
    min_price: float = 50.0
    min_turnover: float = 0.5
    hard_sl_percent: float = 0.05  # 5% below SL = intraday disaster exit

    # Sub-factor weights for trend
    trend_slope_weight: float = 0.6
    trend_distance_200_weight: float = 0.4
    
    # Sub-factor weights for momentum
    momentum_rsi_weight: float = 0.60
    momentum_ppo_weight: float = 0.20
    momentum_ppoh_weight: float = 0.10
    pure_momentum_weight: float = 0.10
    
    # Sub-factor weights for volume
    rvolume_weight: float = 0.7
    price_vol_corr_weight: float = 0.3

    # Sub-factor weights for structure
    percent_b_weight: float = 0.5
    bollinger_width_weight: float = 0.5


class GoldilocksConfig:
    """Non-linear trend scoring zones (distance from 200 EMA)"""
    zone1_end: float = 10  # 0-10% distance
    zone1_score_start: float = 70
    zone1_score_end: float = 85
    zone2_end: float = 35  # 10-35% (sweet spot)
    zone2_score_start: float = 85
    zone2_score_end: float = 100
    zone3_end: float = 50  # 35-50% (extended)
    zone3_score_start: float = 100
    zone3_score_end: float = 60
    zone4_decay: float = 60  # >50% starts at 60, decays to 0


class RSIRegimeConfig:
    """Non-linear RSI scoring zones"""
    zone1_end: float = 40  # < 40 = 0
    zone2_end: float = 50  # 40-50 = 0-30
    zone3_end: float = 70  # 50-70 = 30-100 (sweet spot)
    zone4_end: float = 85  # 70-85 = 100-90
    overbought_floor: float = 60  # > 85 floors at 60
