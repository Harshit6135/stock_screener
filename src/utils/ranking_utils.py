import numpy as np
import pandas as pd

from scipy import stats


def percentile_rank(series: pd.Series) -> pd.Series:
    """
    Calculate percentile rank (0-100) for a series.
    Non-parametric normalization robust to outliers.

    Formula: P_rank = (C_below + 0.5 * C_equal) / N * 100
    
    Parameters:
        series (pd.Series): Input series to rank
    
    Returns:
        pd.Series: Percentile ranks (0-100)
    
    Raises:
        ValueError: If series is empty
    
    Example:
        >>> import pandas as pd
        >>> data = pd.Series([10, 20, 30, 40, 50])
        >>> ranks = percentile_rank(data)
        >>> ranks.iloc[0]  # Lowest value gets 20%
        20.0
        >>> ranks.iloc[4]  # Highest value gets 100%
        100.0
    """
    if series.empty:
        raise ValueError("Cannot rank empty series")
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


def score_rsi_regime(rsi: pd.Series) -> pd.Series:
    """
    Non-linear RSI scoring for momentum context
    RSI 50-70 is the sweet spot (score 100)
    """
    scores = pd.Series(0.0, index=rsi.index)

    scores[rsi < 40] = 0
    scores[(rsi >= 40) & (rsi < 50)] = 25
    scores[(rsi >= 50) & (rsi <= 70)] = 100
    scores[(rsi > 70) & (rsi <= 85)] = 90
    scores[rsi > 85] = 60

    return scores


def score_trend_extension(dist_200: pd.Series) -> pd.Series:
    """
    Goldilocks curve for distance from 200 EMA
    Zone 1 (0-10%): High score
    Zone 2 (10-40%): Maximum score
    Zone 3 (>50%): Degrades (overextended)
    """
    scores = pd.Series(0.0, index=dist_200.index)

    dist_pct = dist_200 * 100

    scores[dist_pct < 0] = 0  # Below 200 EMA
    scores[(dist_pct >= 0) & (dist_pct < 10)] = 80
    scores[(dist_pct >= 10) & (dist_pct <= 40)] = 100
    scores[(dist_pct > 40) & (dist_pct <= 50)] = 70
    scores[dist_pct > 50] = 40  # Overextended

    return scores


def score_percent_b(percent_b: pd.Series) -> pd.Series:
    """
    Score %B position - reward walking the bands
    %B in [0.8, 1.1] = strongest momentum
    """
    scores = pd.Series(0.0, index=percent_b.index)

    scores[percent_b < 0.5] = 20
    scores[(percent_b >= 0.5) & (percent_b < 0.8)] = 60
    scores[(percent_b >= 0.8) & (percent_b <= 1.1)] = 100
    scores[percent_b > 1.1] = 80

    return scores
