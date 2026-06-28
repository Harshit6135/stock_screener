from dataclasses import dataclass


@dataclass
class StrategyParameters:
    """Configuration for factor weights in composite score.

    Factor weights must sum to exactly 1.0 — validated at construction.
    """

    trend_strength_weight: float = 0.30
    momentum_velocity_weight: float = 0.25
    risk_efficiency_weight: float = 0.20
    conviction_weight: float = 0.15
    structure_weight: float = 0.10

    # ATR spike threshold for penalty box (ratio of current ATR / lagged ATR)
    atr_threshold: float = 2.0
    min_price: float = 50.0
    min_turnover: float = 50

    # Sub-factor weights for trend
    trend_slope_weight: float = 0.6
    trend_distance_200_weight: float = 0.4

    # Sub-factor weights for momentum
    momentum_rsi_weight: float = 0.20
    momentum_ppo_weight: float = 0.20
    # momentum_ppoh_weight: float = 0.10
    pure_momentum_weight: float = 0.60

    # Sub-factor weights for volume
    rvolume_weight: float = 0.7
    price_vol_corr_weight: float = 0.3

    # Sub-factor weights for structure
    percent_b_weight: float = 0.5
    bollinger_width_weight: float = 0.5

    def __post_init__(self):
        top_level = (
            self.trend_strength_weight
            + self.momentum_velocity_weight
            + self.risk_efficiency_weight
            + self.conviction_weight
            + self.structure_weight
        )
        if abs(top_level - 1.0) >= 1e-9:
            raise ValueError(
                f"Factor weights must sum to 1.0, got {top_level:.4f}. "
                "Adjust weights so trend + momentum + efficiency + conviction + structure = 1.0"
            )


@dataclass
class GoldilocksConfig:
    """Non-linear trend scoring zones (distance from 200 EMA)"""

    zone1_end: float = 10  # 0–10% distance
    zone1_score_start: float = 70
    zone1_score_end: float = 85
    zone2_end: float = 35  # 10–35% (sweet spot)
    zone2_score_start: float = 85
    zone2_score_end: float = 100
    zone3_end: float = 50  # 35–50% (extended)
    zone3_score_start: float = 100
    zone3_score_end: float = 60
    zone4_decay: float = 60  # >50% starts at 60, decays to 0


@dataclass
class RSIRegimeConfig:
    """Non-linear RSI scoring zones"""

    zone1_end: float = 40  # < 40 = 0
    zone2_end: float = 50  # 40–50 = 0–30
    zone3_end: float = 70  # 50–70 = 30–100 (sweet spot)
    zone4_end: float = 85  # 70–85 = 100–90
    overbought_floor: float = 60  # > 85 floors at 60


@dataclass
class Strategy2Parameters:
    """Configuration for Strategy 2 — Institutional-Grade Multi-Factor Momentum.

    Based on: "Exhaustive Quantitative Evaluation and Optimization of a
    Multi-Factor Momentum Framework for Indian Equities."

    Key differences from Strategy 1:
    - Mansfield RS replaces RSI as primary momentum driver
    - EMA-50 slope is primary trend (70%), EMA-200 dist demoted + Z-score capped
    - Sortino Ratio replaces Sharpe-like risk metric
    - Scaled Turnover added to harvest illiquidity premium
    - ADX global regime multiplier gates capital in choppy markets
    - No global ATR spike or EMA soft-penalty multipliers
    """

    # ── Top-level bucket weights (must sum to 1.0) ───────────────────────────
    trend_strength_weight: float = 0.30
    momentum_velocity_weight: float = 0.25
    risk_efficiency_weight: float = 0.20
    conviction_weight: float = 0.15
    structure_weight: float = 0.10

    # ── Trend sub-factors (reversed vs S1) ───────────────────────────────────
    trend_slope_weight: float = 0.70          # EMA-50 slope is primary
    trend_distance_200_weight: float = 0.30   # EMA-200 dist, Z-score capped
    trend_200_zscore_cap: float = 2.0         # ±σ cap prevents double-penalty

    # ── Momentum sub-factors ─────────────────────────────────────────────────
    mansfield_rs_weight: float = 0.40              # Replaces RSI
    nse_normalized_momentum_weight: float = 0.30   # Vol-adj 6M+12M Z-score
    momentum_ppo_weight: float = 0.20              # PPO (cross-sectional)
    pure_momentum_weight: float = 0.10             # 5-day skip momentum

    # ── Risk Efficiency sub-factors ──────────────────────────────────────────
    sortino_ratio_weight: float = 0.70    # Replaces Sharpe-like metric
    atr_spike_local_weight: float = 0.30  # Local only — no global penalty
    risk_free_rate: float = 0.06          # GoI T-bill proxy (6%)
    sortino_lookback: int = 252           # Annualised (trading days)

    # ── Volume & Liquidity sub-factors ───────────────────────────────────────
    rvolume_weight: float = 0.40          # Relative volume (RVOL)
    scaled_turnover_weight: float = 0.30  # Illiquidity premium (lower = better)
    log_return_corr_weight: float = 0.30  # Log-return price-vol Pearson (20d)

    # ── Structure & Quality sub-factors ──────────────────────────────────────
    quality_zscore_weight: float = 0.50   # ROE, D/E, EPS variability composite
    bollinger_width_weight: float = 0.30  # BB bandwidth expansion
    rsi_entry_filter_weight: float = 0.20 # RSI demoted to entry-timing filter

    # ── ADX Global Regime Multiplier ─────────────────────────────────────────
    adx_weak_threshold: float = 20.0      # ADX < 20 → choppy market
    adx_strong_threshold: float = 30.0    # ADX > 30 → strong but watch exhaustion
    adx_weak_multiplier: float = 0.50     # Suppresses T+M score in chop
    adx_strong_multiplier: float = 0.90   # Minor penalty for late-stage trends
    adx_neutral_multiplier: float = 1.00  # 20 ≤ ADX ≤ 30 → neutral

    # ── Hard exclusions (same as Strategy 1) ─────────────────────────────────
    atr_threshold: float = 2.0
    min_price: float = 50.0
    min_turnover: float = 50   # Cr

    # ── Indicator lookback params ─────────────────────────────────────────────
    mansfield_rs_sma_period: int = 200   # SMA lookback for Mansfield normalisation
    log_corr_lookback: int = 20          # Log-return correlation window

    def __post_init__(self):
        top_level = (
            self.trend_strength_weight
            + self.momentum_velocity_weight
            + self.risk_efficiency_weight
            + self.conviction_weight
            + self.structure_weight
        )
        if abs(top_level - 1.0) >= 1e-9:
            raise ValueError(
                f"Strategy2 factor weights must sum to 1.0, got {top_level:.4f}. "
                "Adjust trend + momentum + efficiency + conviction + structure."
            )
