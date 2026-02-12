class Strategy1Parameters:
    """Configuration for factor weights in composite score"""
    trend_strength_weight: float = 0.30
    momentum_velocity_weight: float = 0.30
    risk_efficiency_weight: float = 0.20
    conviction_weight: float = 0.15
    structure_weight: float = 0.05
    
    # ATR spike threshold for penalty box (ratio of current ATR / lagged ATR)
    atr_threshold: float = 2.0
    
    # Sub-factor weights for trend
    trend_rank_weight: float = 0.6
    trend_extension_rank_weight: float = 0.4
    trend_start_rank_weight: float = 0
    
    # Sub-factor weights for momentum
    momentum_rsi_rank_weight: float = 0.6
    momentum_ppo_rank_weight: float = 0.25
    momentum_ppoh_rank_weight: float = 0.15
    
    # Sub-factor weights for volume
    rvolume_rank_weight: float = 0.7
    price_vol_corr_rank_weight: float = 0.3
    
    # Sub-factor weights for structure
    structure_rank_weight: float = 0.5
    structure_bb_rank_weight: float = 0.5


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


class PenaltyBoxConfig:
    """Disqualification rules (set score=0)"""
    below_ema_200: bool = True
    atr_spike_threshold: float = 2.0
    min_turnover_cr: float = 1.0


class PositionSizingConfig:
    """Position sizing constraints"""
    risk_per_trade_percent: float = 0.01  # 1% portfolio risk
    stop_multiplier: float = 2.0  # ATR multiplier
    max_adv_percent: float = 0.05  # 5% of 20-day ADV
    max_adv_days: int = 20
    concentration_limit: float = 0.12  # 12% max per position
    min_position_percent: float = 0.02  # 2% min position
    sl_fallback_percent: float = 0.06  # 6% fallback when ATR unavailable
    sl_step_percent: float = 0.10  # 10% hard trailing step


class PortfolioControlConfig:
    """Portfolio-level risk controls"""
    drawdown_pause_threshold: float = 0.15  # 15% - pause new entries
    drawdown_reduce_threshold: float = 0.20  # 20% - reduce exposure
    reduce_exposure_factor: float = 0.70  # reduce by 30%
    max_sector_weight: float = 0.40  # 40% max per sector
    correlation_threshold: float = 0.70
    max_correlated_holdings: int = 3


class TaxConfig:
    """Capital gains tax parameters (India)"""
    stcg_rate: float = 0.20  # 20% for < 12 months
    ltcg_rate: float = 0.125  # 12.5% for >= 12 months
    ltcg_exemption: float = 125000  # ₹1.25L per year
    ltcg_holding_days: int = 365
    tax_hold_window_start: int = 300  # bias hold if 300-365 days
    tax_hold_min_score: float = 50


class ChallengerConfig:
    """Challenger vs Incumbent decision parameters"""
    absolute_exit_threshold: float = 40  # exit if score < this
    base_buffer_percent: float = 0.10  # 10% minimum improvement


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


class BacktestConfig:
    """Backtest-specific configuration (fetched from API in production)"""
    initial_capital: float = 100000.0
    max_positions: int = 10
    output_dir: str = "data"