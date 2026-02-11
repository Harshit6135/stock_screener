import pandas as pd
from config import setup_logger
from config.strategies_config import (
    GoldilocksConfig,
    RSIRegimeConfig,
    PenaltyBoxConfig,
    Strategy1Parameters
)

logger = setup_logger(name="FactorsService")


class FactorsService:
    """Factor calculation service with non-linear scoring"""
    
    def __init__(self):
        self.goldilocks = GoldilocksConfig()
        self.rsi_regime = RSIRegimeConfig()
        self.penalty = PenaltyBoxConfig()
        self.weights = Strategy1Parameters()
    
    def calculate_trend_factor(self, close: pd.Series, ema_50: pd.Series, 
                                ema_200: pd.Series) -> pd.Series:
        """
        Goldilocks scoring for distance from 200 EMA
        Non-linear: sweet spot at 10-35% above EMA
        """
        above_200 = (close > ema_200).astype(float)
        dist_200 = ((close - ema_200) / ema_200) * 100
        
        dist_score = dist_200.apply(self._goldilocks_score)
        ema_slope = ((ema_50 - ema_50.shift(5)) / ema_50.shift(5)) * 100
        ema_slope_norm = ema_slope.clip(-5, 5) / 5 * 50 + 50  # normalize to 0-100
        
        # Weighted combination
        trend = above_200 * (
            0.30 * above_200 * 100 +  # binary above check
            0.50 * dist_score +  # distance score
            0.20 * ema_slope_norm  # slope
        )
        return trend
    
    def _goldilocks_score(self, distance: float) -> float:
        """Non-linear distance scoring using configurable zones"""
        cfg = self.goldilocks
        if distance < 0:
            return 0
        elif distance <= cfg.zone1_end:
            # 0-10%: rising from 70 to 85
            return cfg.zone1_score_start + (distance / cfg.zone1_end) * (
                cfg.zone1_score_end - cfg.zone1_score_start)
        elif distance <= cfg.zone2_end:
            # 10-35%: sweet spot, rising from 85 to 100
            progress = (distance - cfg.zone1_end) / (cfg.zone2_end - cfg.zone1_end)
            return cfg.zone2_score_start + progress * (
                cfg.zone2_score_end - cfg.zone2_score_start)
        elif distance <= cfg.zone3_end:
            # 35-50%: extended, declining from 100 to 60
            progress = (distance - cfg.zone2_end) / (cfg.zone3_end - cfg.zone2_end)
            return cfg.zone3_score_start - progress * (
                cfg.zone3_score_start - cfg.zone3_score_end)
        else:
            # >50%: over-extended, decaying from 60 toward 0
            decay = ((distance - cfg.zone3_end) / 50) * cfg.zone4_decay
            return max(0, cfg.zone4_decay - decay)
    
    def calculate_momentum_factor(self, rsi_smooth: pd.Series, ppo: pd.Series,
                                   momentum_3m: pd.Series, momentum_6m: pd.Series) -> pd.Series:
        """
        RSI regime + PPO + pure skip-week momentum
        Uses non-linear RSI scoring
        
        momentum_3m/6m skip last 5 trading days to avoid
        short-term mean-reversion noise (per spec §1.2.G)
        """
        rsi_score = rsi_smooth.apply(self._rsi_regime_score)
        ppo_norm = ppo.clip(-5, 5) / 5 * 50 + 50  # normalize to 0-100
        
        # Pure momentum: average of skip-week 3m and 6m returns
        pure_momentum = ((momentum_3m + momentum_6m) / 2).clip(-50, 50) / 50 * 50 + 50
        
        momentum = (
            0.40 * rsi_score +
            0.30 * ppo_norm +
            0.30 * pure_momentum
        )
        return momentum
    
    def _rsi_regime_score(self, rsi: float) -> float:
        """Non-linear RSI scoring using configurable zones"""
        cfg = self.rsi_regime
        if rsi < cfg.zone1_end:
            return 0
        elif rsi <= cfg.zone2_end:
            # 40-50: 0 to 30
            return ((rsi - cfg.zone1_end) / 10) * 30
        elif rsi <= cfg.zone3_end:
            # 50-70: 30 to 100 (sweet spot)
            return 30 + ((rsi - cfg.zone2_end) / 20) * 70
        elif rsi <= cfg.zone4_end:
            # 70-85: 100 to 90
            return 100 - ((rsi - cfg.zone3_end) / 15) * 10
        else:
            # >85: overbought, dropping from 90 but flooring at 60
            return max(cfg.overbought_floor, 90 - ((rsi - cfg.zone4_end) / 15) * 30)
    
    def calculate_risk_efficiency_factor(self, roc_20: pd.Series, atr: pd.Series,
                                          close: pd.Series, atr_spike: pd.Series) -> pd.Series:
        """
        Risk-adjusted return with ATR spike penalty
        """
        atr_pct = (atr / close) * 100
        risk_adj = roc_20 / atr_pct.replace(0, 0.01)  # avoid div by zero
        
        # Normalize to 0-100
        risk_adj_norm = risk_adj.clip(-5, 5) / 5 * 50 + 50
        
        # Apply spike penalty
        spike_penalty = (atr_spike > self.penalty.atr_spike_threshold).astype(float)
        efficiency = risk_adj_norm * (1 - spike_penalty * 0.5)  # reduce by 50% if spiking
        
        return efficiency
    
    def calculate_volume_factor(self, rvol: pd.Series, 
                                 vol_price_corr: pd.Series) -> pd.Series:
        """
        RVOL capped at 3x + volume-price correlation
        """
        rvol_capped = rvol.clip(0, 3)
        rvol_norm = rvol_capped / 3 * 100  # 0-100
        
        corr_norm = (vol_price_corr.clip(-1, 1) + 1) / 2 * 100  # -1,1 -> 0,100
        
        volume = (
            0.60 * rvol_norm +
            0.40 * corr_norm
        )
        return volume
    
    def calculate_structure_factor(self, percent_b: pd.Series,
                                    bandwidth: pd.Series) -> pd.Series:
        """
        %B scoring + bandwidth expansion
        """
        b_score = percent_b.apply(self._b_score)
        
        # Bandwidth change indicates volatility expansion
        bw_change = bandwidth.pct_change(5).fillna(0)
        bw_score = bw_change.clip(-0.5, 0.5) / 0.5 * 50 + 50  # normalize
        
        structure = (
            0.70 * b_score +
            0.30 * bw_score
        )
        return structure
    
    def _b_score(self, b_val: float) -> float:
        """Bollinger %B scoring"""
        if pd.isna(b_val):
            return 50
        elif b_val < 0.5:
            return 20
        elif b_val <= 0.7:
            return 20 + ((b_val - 0.5) / 0.2) * 40
        elif b_val <= 1.1:
            return 60 + ((b_val - 0.7) / 0.4) * 40
        else:
            return max(70, 100 - ((b_val - 1.1) / 0.5) * 30)
    
    def calculate_all_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all factors for a DataFrame with indicator columns
        Expects columns: close, ema_50, ema_200, rsi_signal_ema_3, ppo_12_26_9,
                        roc_60, roc_125, roc_20, atrr_14, atr_spike, rvol,
                        price_vol_correlation, percent_b, bbb_20_2_2
        """
        df = df.copy()
        
        df['factor_trend'] = self.calculate_trend_factor(
            df['close'], df['ema_50'], df['ema_200'])
        
        df['factor_momentum'] = self.calculate_momentum_factor(
            df['rsi_signal_ema_3'], df['ppo_12_26_9'], 
            df['momentum_3m'], df['momentum_6m'])
        
        df['factor_efficiency'] = self.calculate_risk_efficiency_factor(
            df['roc_20'], df['atrr_14'], df['close'], df['atr_spike'])
        
        df['factor_volume'] = self.calculate_volume_factor(
            df['rvol'], df['price_vol_correlation'])
        
        df['factor_structure'] = self.calculate_structure_factor(
            df['percent_b'], df['bbb_20_2_2'])
        
        return df
