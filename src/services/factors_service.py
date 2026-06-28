import pandas as pd

from config import Strategy2Parameters, StrategyParameters, setup_logger
from utils import goldilocks_score, rsi_regime_score, score_percent_b

logger = setup_logger(name="FactorsService")
pd.set_option("future.no_silent_downcasting", True)


class FactorsService:
    """Factor calculation service with non-linear scoring (Strategy 1)"""

    def __init__(self):
        self.weights = StrategyParameters()

    def calculate_trend_factor(
        self, distance_from_ema_200: pd.Series, ema_50_slope: pd.Series
    ) -> pd.Series:
        """
        Goldilocks scoring for distance from 200 EMA
        Non-linear: sweet spot at 10-35% above EMA
        """
        dist_score = distance_from_ema_200.apply(goldilocks_score)
        ema_slope_norm = ema_50_slope.clip(-5, 5) / 5 * 50 + 50

        trend = (
            self.weights.trend_distance_200_weight * dist_score
            + self.weights.trend_slope_weight * ema_slope_norm
        )
        return trend

    def calculate_momentum_factor(
        self,
        rsi_smooth: pd.Series,
        ppo: pd.Series,
        ppoh: pd.Series,
        momentum_3m: pd.Series,
        momentum_6m: pd.Series,
    ) -> pd.Series:
        """
        RSI regime + PPO + pure skip-week momentum
        Uses non-linear RSI scoring

        momentum_3m/6m skip last 5 trading days to avoid
        short-term mean-reversion noise (per spec §1.2.G)
        """
        rsi_score = rsi_smooth.apply(rsi_regime_score)
        ppo_norm = ppo.clip(-5, 5) / 5 * 50 + 50
        ppoh_norm = ppoh.clip(-5, 5) / 5 * 50 + 50
        pure_momentum = ((momentum_3m + momentum_6m) / 2).clip(-50, 50) / 50 * 50 + 50

        momentum = (
            self.weights.momentum_rsi_weight * rsi_score
            + self.weights.momentum_ppo_weight * ppo_norm
            + self.weights.momentum_ppoh_weight * ppoh_norm
            + self.weights.pure_momentum_weight * pure_momentum
        )
        return momentum

    def calculate_risk_efficiency_factor(
        self, risk_adjusted_return: pd.Series, atr_spike: pd.Series
    ) -> pd.Series:
        """
        Risk-adjusted return with ATR spike penalty
        """
        risk_adj_norm = risk_adjusted_return.clip(-5, 5) / 5 * 50 + 50

        spike_penalty = (atr_spike > self.weights.atr_threshold).astype(float)
        efficiency = risk_adj_norm * (1 - spike_penalty * 0.5)

        return efficiency

    def calculate_volume_factor(self, rvol: pd.Series, vol_price_corr: pd.Series) -> pd.Series:
        """
        RVOL capped at 3x + volume-price correlation
        """
        rvol_capped = rvol.clip(0, 3)
        rvol_norm = rvol_capped / 3 * 100
        corr_norm = (vol_price_corr.clip(-1, 1) + 1) / 2 * 100

        volume = (
            self.weights.rvolume_weight * rvol_norm + self.weights.price_vol_corr_weight * corr_norm
        )
        return volume

    def calculate_structure_factor(self, percent_b: pd.Series, bandwidth: pd.Series) -> pd.Series:
        """
        %B scoring + bandwidth expansion
        """
        b_score = percent_b.apply(score_percent_b)

        bw_change = bandwidth.pct_change(5).fillna(0)
        bw_score = bw_change.clip(-0.5, 0.5) / 0.5 * 50 + 50

        structure = (
            self.weights.percent_b_weight * b_score + self.weights.bollinger_width_weight * bw_score
        )
        return structure

    def calculate_all_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all factors for a DataFrame with indicator columns
        Expects columns: close, ema_50, ema_200, rsi_signal_ema_3, ppo_12_26_9,
                        roc_60, roc_125, roc_20, atrr_14, atr_spike, rvol,
                        price_vol_correlation, percent_b, bbb_20_2_2
        """

        df["factor_trend"] = self.calculate_trend_factor(
            df["distance_from_ema_200"], df["ema_50_slope"]
        )

        df["factor_momentum"] = self.calculate_momentum_factor(
            df["rsi_signal_ema_3"],
            df["ppo_12_26_9"],
            df["ppoh_12_26_9"],
            df["momentum_3m"],
            df["momentum_6m"],
        )

        df["factor_efficiency"] = self.calculate_risk_efficiency_factor(
            df["risk_adjusted_return"], df["atr_spike"]
        )

        df["factor_volume"] = self.calculate_volume_factor(df["rvol"], df["price_vol_correlation"])

        df["factor_structure"] = self.calculate_structure_factor(df["percent_b"], df["bbb_20_2_2"])

        return df


# =============================================================================
# Strategy 2 — Institutional-Grade Multi-Factor Momentum
# =============================================================================


class FactorsServiceV2:
    """Factor calculation service for Strategy 2.

    Key differences from Strategy 1:
    - Trend: EMA-50 slope primary (70%), EMA-200 dist cross-sectionally Z-score capped (30%)
    - Momentum: Mansfield RS + NSE normalised momentum + PPO + pure momentum
    - Risk Efficiency: Sortino Ratio (70%) + local ATR spike (30%)
    - Volume: RVOL + inverted Scaled Turnover (illiquidity premium) + log-return correlation
    - Structure: Quality Z-Score + BB width + RSI entry filter
    """

    def __init__(self):
        self.weights = Strategy2Parameters()

    def calculate_trend_factor(
        self, distance_from_ema_200: pd.Series, ema_50_slope: pd.Series
    ) -> pd.Series:
        """EMA-50 slope is primary (70%); EMA-200 distance Z-score capped (30%).

        Cross-sectional Z-score cap prevents stocks very far from EMA-200
        from being double-penalised (they're already low score in momentum).
        """
        # EMA-50 slope: normalise to [0, 100]
        slope_norm = ema_50_slope.clip(-5, 5) / 5 * 50 + 50

        # EMA-200 distance: cross-sectional Z-score, capped at ±cap, rescaled to [0, 100]
        cap = self.weights.trend_200_zscore_cap
        mu = distance_from_ema_200.mean()
        sigma = distance_from_ema_200.std()
        if sigma > 0:
            dist_z = ((distance_from_ema_200 - mu) / sigma).clip(-cap, cap)
        else:
            dist_z = pd.Series(0.0, index=distance_from_ema_200.index)
        dist_score = (dist_z + cap) / (2 * cap) * 100  # maps [-cap, cap] → [0, 100]

        return (
            self.weights.trend_slope_weight * slope_norm
            + self.weights.trend_distance_200_weight * dist_score
        )

    def calculate_momentum_factor(
        self,
        mansfield_rs: pd.Series,
        nse_norm_momentum: pd.Series,
        ppo: pd.Series,
        momentum_6m: pd.Series,
    ) -> pd.Series:
        """Mansfield RS + vol-adj NSE momentum + PPO + pure 6M momentum."""
        # Mansfield RS: clip to ±2, rescale to [0, 100]
        mrs_norm = mansfield_rs.clip(-2, 2) / 2 * 50 + 50

        # NSE Normalised Momentum: cross-sectional Z-score, clip ±3
        mu = nse_norm_momentum.mean()
        sigma = nse_norm_momentum.std()
        if sigma > 0:
            mom_z = ((nse_norm_momentum - mu) / sigma).clip(-3, 3)
        else:
            mom_z = pd.Series(0.0, index=nse_norm_momentum.index)
        mom_norm = mom_z / 3 * 50 + 50  # [0, 100]

        # PPO
        ppo_norm = ppo.clip(-5, 5) / 5 * 50 + 50

        # Pure 6-month momentum
        pm_norm = momentum_6m.clip(-50, 50) / 50 * 50 + 50

        return (
            self.weights.mansfield_rs_weight * mrs_norm
            + self.weights.nse_normalized_momentum_weight * mom_norm
            + self.weights.momentum_ppo_weight * ppo_norm
            + self.weights.pure_momentum_weight * pm_norm
        )

    def calculate_risk_efficiency_factor(
        self, sortino_ratio: pd.Series, atr_spike: pd.Series
    ) -> pd.Series:
        """Sortino Ratio (70%) + local ATR spike filter (30%).

        No global multiplier — penalisation is localised to this factor bucket.
        """
        # Sortino: clip to [-5, 5], rescale to [0, 100]
        sortino_norm = sortino_ratio.clip(-5, 5) / 5 * 50 + 50

        # Local ATR spike: binary 0/1 → score [50, 100]
        spike_flag = (atr_spike > self.weights.atr_threshold).astype(float)
        atr_score = (1 - spike_flag * 0.5) * 100  # 100 clean, 50 spiking

        return (
            self.weights.sortino_ratio_weight * sortino_norm
            + self.weights.atr_spike_local_weight * atr_score
        )

    def calculate_volume_factor(
        self,
        rvol: pd.Series,
        scaled_turnover: pd.Series,
        log_price_vol_corr: pd.Series,
    ) -> pd.Series:
        """RVOL + inverted Scaled Turnover (illiquidity premium) + log-return corr."""
        rvol_norm = rvol.clip(0, 3) / 3 * 100

        # Scaled Turnover: lower = better (illiquid momentum premium)
        st_clipped = scaled_turnover.clip(0, 1)
        st_inv = (1 - st_clipped) * 100

        # Log-return price-vol correlation: map [-1, 1] → [0, 100]
        corr_norm = (log_price_vol_corr.clip(-1, 1) + 1) / 2 * 100

        return (
            self.weights.rvolume_weight * rvol_norm
            + self.weights.scaled_turnover_weight * st_inv
            + self.weights.log_return_corr_weight * corr_norm
        )

    def calculate_structure_factor(
        self,
        quality_z_score: pd.Series,
        bandwidth: pd.Series,
        rsi_14: pd.Series,
    ) -> pd.Series:
        """Quality Z-Score + BB bandwidth expansion + RSI entry filter."""
        # Quality Z-score: clip [-3, 3] → [0, 100]
        q_norm = quality_z_score.clip(-3, 3) / 3 * 50 + 50

        # BB bandwidth change (5-day)
        bw_change = bandwidth.pct_change(5).fillna(0)
        bw_score = bw_change.clip(-0.5, 0.5) / 0.5 * 50 + 50

        # RSI as entry-timing filter: already [0, 100]
        rsi_norm = rsi_14.clip(0, 100)

        return (
            self.weights.quality_zscore_weight * q_norm
            + self.weights.bollinger_width_weight * bw_score
            + self.weights.rsi_entry_filter_weight * rsi_norm
        )

    def calculate_all_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all Strategy 2 factors.

        Expects the DataFrame to contain both S1 and S2 indicator columns
        (merged by PercentileService before calling).

        Required columns:
            S1: distance_from_ema_200, ema_50_slope, ppo_12_26_9, momentum_6m,
                atr_spike, rvol, bbb_20_2_2, rsi_14
            S2: mansfield_rs, nse_norm_momentum, sortino_ratio,
                scaled_turnover, log_price_vol_corr, quality_z_score
        """
        df["factor_trend"] = self.calculate_trend_factor(
            df["distance_from_ema_200"], df["ema_50_slope"]
        )

        df["factor_momentum"] = self.calculate_momentum_factor(
            df["mansfield_rs"].fillna(0),
            df["nse_norm_momentum"].fillna(0),
            df["ppo_12_26_9"].fillna(0),
            df["momentum_6m"].fillna(0),
        )

        df["factor_efficiency"] = self.calculate_risk_efficiency_factor(
            df["sortino_ratio"].fillna(0),
            df["atr_spike"].fillna(1),
        )

        df["factor_volume"] = self.calculate_volume_factor(
            df["rvol"].fillna(1),
            df["scaled_turnover"].fillna(0.5),
            df["log_price_vol_corr"].fillna(0),
        )

        df["factor_structure"] = self.calculate_structure_factor(
            df["quality_z_score"].fillna(0),
            df["bbb_20_2_2"].fillna(0),
            df["rsi_14"].fillna(50),
        )

        return df
