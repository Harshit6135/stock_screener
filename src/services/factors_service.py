import pandas as pd

from config import setup_logger, StrategyParameters
from utils import goldilocks_score, rsi_regime_score, score_percent_b


logger = setup_logger(name="FactorsService")
pd.set_option('future.no_silent_downcasting', True)


class FactorsService:
    """Factor calculation service with non-linear scoring"""
    def __init__(self):
        self.weights = StrategyParameters()

    def calculate_trend_factor(self, 
                               distance_from_ema_200: pd.Series, 
                               ema_50_slope: pd.Series) -> pd.Series:
        """
        Goldilocks scoring for distance from 200 EMA
        Non-linear: sweet spot at 10-35% above EMA
        """
        dist_score = distance_from_ema_200.apply(goldilocks_score)
        ema_slope_norm = ema_50_slope.clip(-5, 5) / 5 * 50 + 50

        trend = (
             self.weights.trend_distance_200_weight * dist_score +
             self.weights.trend_slope_weight * ema_slope_norm
        )
        return trend

    def calculate_momentum_factor(self, rsi_smooth: pd.Series, ppo: pd.Series, ppoh: pd.Series,
                                   momentum_3m: pd.Series, momentum_6m: pd.Series) -> pd.Series:
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
            self.weights.momentum_rsi_weight * rsi_score +
            self.weights.momentum_ppo_weight * ppo_norm +
            self.weights.momentum_ppoh_weight * ppoh_norm +
            self.weights.pure_momentum_weight * pure_momentum
        )
        return momentum

    def calculate_risk_efficiency_factor(self, risk_adjusted_return: pd.Series, atr_spike: pd.Series) -> pd.Series:
        """
        Risk-adjusted return with ATR spike penalty
        """
        risk_adj_norm = risk_adjusted_return.clip(-5, 5) / 5 * 50 + 50
        
        spike_penalty = (atr_spike > self.weights.atr_threshold).astype(float)
        efficiency = risk_adj_norm * (1 - spike_penalty * 0.5)
        
        return efficiency

    def calculate_volume_factor(self, rvol: pd.Series, 
                                 vol_price_corr: pd.Series) -> pd.Series:
        """
        RVOL capped at 3x + volume-price correlation
        """
        rvol_capped = rvol.clip(0, 3)
        rvol_norm = rvol_capped / 3 * 100
        corr_norm = (vol_price_corr.clip(-1, 1) + 1) / 2 * 100
        
        volume = (
            self.weights.rvolume_weight * rvol_norm +
            self.weights.price_vol_corr_weight * corr_norm
        )
        return volume

    def calculate_structure_factor(self, percent_b: pd.Series,
                                    bandwidth: pd.Series) -> pd.Series:
        """
        %B scoring + bandwidth expansion
        """
        b_score = percent_b.apply(score_percent_b)
        
        bw_change = bandwidth.pct_change(5).fillna(0)
        bw_score = bw_change.clip(-0.5, 0.5) / 0.5 * 50 + 50
        
        structure = (
            self.weights.percent_b_weight * b_score +
            self.weights.bollinger_width_weight * bw_score
        )
        return structure

    def calculate_all_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all factors for a DataFrame with indicator columns
        Expects columns: close, ema_50, ema_200, rsi_signal_ema_3, ppo_12_26_9,
                        roc_60, roc_125, roc_20, atrr_14, atr_spike, rvol,
                        price_vol_correlation, percent_b, bbb_20_2_2
        """

        df['factor_trend'] = self.calculate_trend_factor(
            df['distance_from_ema_200'], df['ema_50_slope'])
        
        df['factor_momentum'] = self.calculate_momentum_factor(
            df['rsi_signal_ema_3'], df['ppo_12_26_9'], df['ppoh_12_26_9'],
            df['momentum_3m'], df['momentum_6m'])
        
        df['factor_efficiency'] = self.calculate_risk_efficiency_factor(
            df['risk_adjusted_return'], df['atr_spike'])
        
        df['factor_volume'] = self.calculate_volume_factor(
            df['rvol'], df['price_vol_correlation'])
        
        df['factor_structure'] = self.calculate_structure_factor(
            df['percent_b'], df['bbb_20_2_2'])
        
        return df
