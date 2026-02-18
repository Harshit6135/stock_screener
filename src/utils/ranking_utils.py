import numpy as np
import pandas as pd

from scipy import stats

from config import GoldilocksConfig, RSIRegimeConfig


def percentile_rank(series: pd.Series) -> pd.Series:
    """
    Calculate percentile rank (0-100) for a series
    Non-parametric normalization robust to outliers

    Formula: P_rank = (C_below + 0.5 * C_equal) / N * 100
    """
    return series.rank(pct=True) * 100


def z_score_normalize(series: pd.Series, cap_at: float = 3.0) -> pd.Series:
    """
    Z-Score normalization with winsorization
    Maps to 0-100 scale: Score = 50 + (Z * 16.66)
    """
    z_scores = stats.zscore(series, nan_policy='omit')
    z_scores = np.clip(z_scores, -cap_at, cap_at)
    normalized = 50 + (z_scores * 16.66)
    return pd.Series(np.clip(normalized, 0, 100), index=series.index)


def rsi_regime_score(rsi: float) -> float:
    """Non-linear RSI scoring using configurable zones"""
    cfg = RSIRegimeConfig()
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


def goldilocks_score(distance: float) -> float:
    """Non-linear distance scoring using configurable zones"""
    cfg = GoldilocksConfig()
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


def score_percent_b(b_val: float) -> float:
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
