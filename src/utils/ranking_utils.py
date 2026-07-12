"""
Ranking Utilities

Non-linear scoring functions used by FactorsService / PercentileService to
transform raw indicator values into normalised [0, 100] factor scores.

All scoring functions are pure (no side effects) and operate element-wise
on pandas Series via .apply() or directly on scalar float values.
"""

import pandas as pd

from config import GoldilocksConfig, RSIRegimeConfig

# Module-level singletons — immutable configs, no need to re-create per call
_RSI_CONFIG = RSIRegimeConfig()
_GOLDILOCKS_CONFIG = GoldilocksConfig()


def percentile_rank(series: pd.Series) -> pd.Series:
    """
    Compute cross-sectional percentile rank (0-100) for a pandas Series.

    Uses pandas ``rank(pct=True)`` which implements the formula:

        P_rank = (count_below + 0.5 * count_equal) / N * 100

    This is non-parametric (no assumptions about distribution shape) and
    robust to outliers — a single extreme value does not compress all
    other values into a narrow range.

    The result is 0-100 rather than 0-1 so it integrates naturally with
    the Goldilocks and RSI regime scores which are also on the 0-100 scale.

    Parameters
    ----------
    series : pd.Series
        Raw indicator values for a single factor across all stocks on one date.

    Returns
    -------
    pd.Series
        Percentile rank in [0, 100].
    """
    return series.rank(pct=True) * 100




def rsi_regime_score(rsi: float) -> float:
    """
    Convert a raw RSI value into a 0-100 regime score.

    Zone breakdown (configured via ``RSIRegimeConfig``):

    ============  =====  ====================================================
    RSI range     Score  Interpretation
    ============  =====  ====================================================
    < 40          0      Weak momentum / oversold; avoid
    40 – 50       0-30   Building momentum; marginal
    50 – 70       30-100 **Sweet spot**: strong, sustainable momentum
    70 – 85       100-90 Slightly overbought; still acceptable
    > 85           90→60  Overbought; scores decline but floor at 60
    ============  =====  ====================================================

    The non-linear piecewise structure rewards stocks in the 50-70 RSI
    zone disproportionately, matching the empirical finding that momentum
    stocks sustain their trend best in this range.

    Parameters
    ----------
    rsi : float
        RSI value (0-100 scale from pandas_ta).

    Returns
    -------
    float
        Regime score in [0, 100].
    """
    cfg = _RSI_CONFIG
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
    """
    Convert EMA-200 distance into a 0-100 Goldilocks trend score.

    The name refers to the "not too hot, not too cold" concept: stocks
    that are too far above EMA200 are over-extended (momentum exhaustion
    risk), while stocks below EMA200 are in a downtrend.

    Zone breakdown (configured via ``GoldilocksConfig``):

    ===========  =======  ====================================================
    Distance     Score    Interpretation
    ===========  =======  ====================================================
    < 0          0        Below EMA200; downtrend; avoid
    0 – 10%      70-85    Early breakout; trend forming but not confirmed
    10 – 35%     85-100   **Sweet spot**: confirmed uptrend, not over-extended
    35 – 50%     100-60   Extended; possible mean-reversion risk
    > 50%         60→0    Over-extended; high reversion risk; score decays
    ===========  =======  ====================================================

    Parameters
    ----------
    distance : float
        Fractional EMA distance: ``(Close - EMA200) / EMA200``.
        Positive means price is above EMA; negative means below.

    Returns
    -------
    float
        Goldilocks score in [0, 100].
    """
    cfg = _GOLDILOCKS_CONFIG
    if distance < 0:
        return 0
    elif distance <= cfg.zone1_end:
        # 0-10%: rising from 70 to 85
        return cfg.zone1_score_start + (distance / cfg.zone1_end) * (
            cfg.zone1_score_end - cfg.zone1_score_start
        )
    elif distance <= cfg.zone2_end:
        # 10-35%: sweet spot, rising from 85 to 100
        progress = (distance - cfg.zone1_end) / (cfg.zone2_end - cfg.zone1_end)
        return cfg.zone2_score_start + progress * (cfg.zone2_score_end - cfg.zone2_score_start)
    elif distance <= cfg.zone3_end:
        # 35-50%: extended, declining from 100 to 60
        progress = (distance - cfg.zone2_end) / (cfg.zone3_end - cfg.zone2_end)
        return cfg.zone3_score_start - progress * (cfg.zone3_score_start - cfg.zone3_score_end)
    else:
        # >50%: over-extended, decaying from 60 toward 0
        decay = ((distance - cfg.zone3_end) / 50) * cfg.zone4_decay
        return max(0, cfg.zone4_decay - decay)


def score_percent_b(b_val: float) -> float:
    """
    Convert a Bollinger Band %B value into a 0-100 structure score.

    %B measures where the closing price is within the Bollinger Band:

    - 0.0 = at lower band (oversold)
    - 0.5 = at the midline (20-day SMA)
    - 1.0 = at upper band (overbought)

    Zone scoring:

    ==========  =======  ====================================================
    %B value    Score    Interpretation
    ==========  =======  ====================================================
    NaN         50       Missing data — neutral score
    < 0.5       20       Below midline; weak price structure
    0.5 – 0.7   20-60    Approaching upper half; building structure
    0.7 – 1.1   60-100   Strong structure; price in upper band region
    > 1.1       100-70   Price above band (strong but possible overextension)
    ==========  =======  ====================================================

    Parameters
    ----------
    b_val : float
        %B value as computed by ``IndicatorsService.calculate_percent_b``.

    Returns
    -------
    float
        Structure score in [20, 100] (or 50 for NaN).
    """
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
