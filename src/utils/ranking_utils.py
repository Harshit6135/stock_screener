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
