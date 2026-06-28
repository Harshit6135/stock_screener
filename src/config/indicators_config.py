"""
Indicator configuration: pandas_ta Studies, the Indicator Registry,
and compute functions for derived indicators.

Adding a new indicator:
  1. Write a _compute_<name>(df, **kwargs) -> pd.Series function below.
  2. Register it in INDICATOR_REGISTRY with a DerivedIndicator entry.
  3. Add the column to IndicatorsModel.
  4. Run `flask db migrate && flask db upgrade`.
  5. POST /api/v1/indicators/patch {"indicators": ["<name>"]} to backfill.
"""

from dataclasses import dataclass, field
from typing import Callable, List

import numpy as np
import pandas as pd
import pandas_ta as ta

# =============================================================================
# pandas_ta Studies (unchanged from Strategy 1)
# =============================================================================

ema_strategy = ta.Study(
    name="EMA Strategy",
    description="200-day EMA — needs full history, run first",
    cores=0,
    ta=[
        {"kind": "ema", "length": 200},
    ],
)

momentum_strategy = ta.Study(
    name="Momentum Strategy",
    description="Combines trend, momentum, and volatility indicators",
    cores=0,
    ta=[
        {"kind": "ema", "length": 50},
        {"kind": "rsi", "length": 14},
        {"kind": "roc", "length": 10},
        {"kind": "roc", "length": 20},
        {"kind": "roc", "length": 60},
        {"kind": "roc", "length": 125},
        {"kind": "sma", "length": 20},
        {"kind": "stoch", "k": 14, "d": 3},
        {"kind": "ppo", "fast": 12, "slow": 26, "signal": 9},
        {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
        {"kind": "bbands", "length": 20, "std": 2},
        {"kind": "atr", "length": 14},
        {"kind": "sma", "length": 20, "close": "volume", "prefix": "VOL"},
        {"kind": "ema", "length": 20, "close": "avg_turnover", "prefix": "AVG_TURNOVER"},
    ],
)

derived_strategy = ta.Study(
    name="Derived Strategy",
    description="Derived columns from momentum strategy",
    cores=0,
    ta=[{"kind": "ema", "length": 3, "close": "RSI_14", "prefix": "RSI_SIGNAL"}],
)

# Strategy 2: ADX — focused single-indicator study, runs independently
strategy2_adx_study = ta.Study(
    name="Strategy 2 ADX",
    description="ADX 14-period for S2 regime multiplier",
    cores=0,
    ta=[{"kind": "adx", "length": 14}],
)

# =============================================================================
# Additional parameters (shared across strategies)
# =============================================================================

additional_parameters = {
    "vol_price_lookback": 10,       # S1 price-vol correlation window
    "ema_slope_lookback": 5,
    "truncate_days": 365,
    "ema_200_lookback": 900,
    "log_corr_lookback": 20,        # S2 log-return correlation window
    "sortino_lookback": 252,        # S2 Sortino annualisation window
    "mansfield_rs_sma": 200,        # S2 Mansfield RS normalisation SMA
}

# =============================================================================
# Indicator Registry dataclasses
# =============================================================================


@dataclass
class PandasTaIndicator:
    """Indicator produced by a pandas_ta Study run.

    study_name: key into STUDY_MAP below
    output_col: raw column name as produced by pandas_ta (before lowercasing)
    """

    study_name: str
    output_col: str


@dataclass
class DerivedIndicator:
    """Indicator computed by a pure-Python function from OHLCV / existing columns.

    fn       : callable(df, **kwargs) -> pd.Series  (index = df.index)
    deps     : list of column names the function reads from df
    needs_benchmark: if True, fn receives benchmark=<pd.Series> keyword arg
    """

    fn: Callable
    deps: List[str]
    needs_benchmark: bool = False


# =============================================================================
# Strategy 2 compute functions
# =============================================================================


def _compute_adx_14(df: pd.DataFrame) -> pd.Series:
    """ADX 14-period via pandas_ta single-function call."""
    result = ta.adx(df["high"], df["low"], df["close"], length=14)
    if result is None or "ADX_14" not in result.columns:
        return pd.Series(np.nan, index=df.index)
    return result["ADX_14"]


def _compute_mansfield_rs(df: pd.DataFrame, benchmark: pd.Series) -> pd.Series:
    """Mansfield Relative Strength vs Nifty 500.

    RS  = (close / benchmark) - 1
    MRS = RS / RS.rolling(200).mean() - 1
    Values > 0: outperforming benchmark.
    """
    bench = benchmark.reindex(df.index, method="ffill")
    rp = (df["close"] / bench) - 1
    sma = rp.rolling(additional_parameters["mansfield_rs_sma"]).mean()
    return (rp / sma.replace(0, np.nan)) - 1


def _compute_nse_norm_momentum(df: pd.DataFrame) -> pd.Series:
    """NSE Normalized Momentum Score.

    Volatility-adjusted composite of 6-month and 12-month log returns.
    Raw value — cross-sectionally Z-scored inside FactorsServiceV2.
    """
    log_ret = np.log(df["close"] / df["close"].shift(1))
    sigma_ann = log_ret.rolling(252).std() * np.sqrt(252)
    sigma_ann = sigma_ann.replace(0, np.nan)
    ret_6m = np.log(df["close"].shift(5) / df["close"].shift(126))
    ret_12m = np.log(df["close"].shift(5) / df["close"].shift(252))
    return ((ret_6m / sigma_ann) + (ret_12m / sigma_ann)) / 2


def _compute_sortino_ratio(df: pd.DataFrame) -> pd.Series:
    """Sortino Ratio — annualised, rf = 6% (GoI T-bill proxy).

    Only penalises downside volatility; ignores positive returns.
    Lookback: 252 trading days.
    """
    rf_daily = 0.06 / 252
    daily_ret = df["close"].pct_change()
    downside = daily_ret.where(daily_ret < rf_daily, other=np.nan)
    dd_std = downside.rolling(252).std() * np.sqrt(252)
    ann_ret = daily_ret.rolling(252).mean() * 252
    return (ann_ret - 0.06) / dd_std.replace(0, np.nan)


def _compute_scaled_turnover(df: pd.DataFrame) -> pd.Series:
    """Scaled Turnover = daily_turnover / (close × vol_sma_20).

    Proxy for share of total float changing hands daily.
    Lower value → illiquid momentum stock → historically higher alpha.
    Clipped to [0, 1] before scoring.
    """
    daily_turnover = df["close"] * df["volume"]
    vol_sma20 = df["volume"].rolling(20).mean()
    market_cap_proxy = df["close"] * vol_sma20
    return daily_turnover / market_cap_proxy.replace(0, np.nan)


def _compute_log_price_vol_corr(df: pd.DataFrame) -> pd.Series:
    """20-day Pearson correlation between log returns and volume.

    Uses stationary log returns (not raw prices) to avoid spurious correlation.
    Positive = accumulation, Negative = distribution.
    """
    log_ret = np.log(df["close"] / df["close"].shift(1))
    lookback = additional_parameters["log_corr_lookback"]
    return log_ret.rolling(lookback).corr(df["volume"])


def _compute_momentum_12m(df: pd.DataFrame) -> pd.Series:
    """12-month return with 5-day skip to avoid short-term reversal noise."""
    return (df["close"].shift(5) / df["close"].shift(252)) - 1


def _compute_quality_z_score(_df: pd.DataFrame) -> pd.Series:
    """Quality Z-Score placeholder (0.0) until fundamental data is integrated.

    Future: composite Z-score of ROE, D/E ratio, EPS growth variability
    matching Nifty 100 Quality 30 Index methodology.
    """
    return pd.Series(0.0, index=_df.index)


# =============================================================================
# Indicator Registry
# =============================================================================
# Maps indicator column name (as stored in indicators table) to its definition.
# PandasTaIndicators are grouped by study_name and run once per study.
# DerivedIndicators are computed independently in dependency order.

INDICATOR_REGISTRY: dict = {
    # ── pandas_ta: EMA study ─────────────────────────────────────────────────
    "ema_200": PandasTaIndicator("ema_strategy", "EMA_200"),

    # ── pandas_ta: momentum study ────────────────────────────────────────────
    "ema_50":           PandasTaIndicator("momentum_strategy", "EMA_50"),
    "rsi_14":           PandasTaIndicator("momentum_strategy", "RSI_14"),
    "roc_10":           PandasTaIndicator("momentum_strategy", "ROC_10"),
    "roc_20":           PandasTaIndicator("momentum_strategy", "ROC_20"),
    "roc_60":           PandasTaIndicator("momentum_strategy", "ROC_60"),
    "roc_125":          PandasTaIndicator("momentum_strategy", "ROC_125"),
    "sma_20":           PandasTaIndicator("momentum_strategy", "SMA_20"),
    "stochk_14_3_3":    PandasTaIndicator("momentum_strategy", "STOCHk_14_3_3"),
    "stochd_14_3_3":    PandasTaIndicator("momentum_strategy", "STOCHd_14_3_3"),
    "ppo_12_26_9":      PandasTaIndicator("momentum_strategy", "PPO_12_26_9"),
    "ppoh_12_26_9":     PandasTaIndicator("momentum_strategy", "PPOh_12_26_9"),
    "ppos_12_26_9":     PandasTaIndicator("momentum_strategy", "PPOs_12_26_9"),
    "macd_12_26_9":     PandasTaIndicator("momentum_strategy", "MACD_12_26_9"),
    "macdh_12_26_9":    PandasTaIndicator("momentum_strategy", "MACDh_12_26_9"),
    "macds_12_26_9":    PandasTaIndicator("momentum_strategy", "MACDs_12_26_9"),
    "bbl_20_2_2":       PandasTaIndicator("momentum_strategy", "BBL_20_2.0_2.0"),
    "bbm_20_2_2":       PandasTaIndicator("momentum_strategy", "BBM_20_2.0_2.0"),
    "bbu_20_2_2":       PandasTaIndicator("momentum_strategy", "BBU_20_2.0_2.0"),
    "bbb_20_2_2":       PandasTaIndicator("momentum_strategy", "BBB_20_2.0_2.0"),
    "bbp_20_2_2":       PandasTaIndicator("momentum_strategy", "BBP_20_2.0_2.0"),
    "atrr_14":          PandasTaIndicator("momentum_strategy", "ATRr_14"),
    "vol_sma_20":       PandasTaIndicator("momentum_strategy", "VOL_SMA_20"),
    "avg_turnover_ema_20": PandasTaIndicator("momentum_strategy", "AVG_TURNOVER_EMA_20"),

    # ── pandas_ta: derived study ─────────────────────────────────────────────
    "rsi_signal_ema_3": PandasTaIndicator("derived_strategy", "RSI_SIGNAL_EMA_3"),

    # ── pandas_ta: Strategy 2 ADX (standalone study) ─────────────────────────
    "adx_14": PandasTaIndicator("strategy2_adx_study", "ADX_14"),

    # ── Derived: Strategy 1 ───────────────────────────────────────────────────
    "price_vol_correlation": DerivedIndicator(
        fn=lambda df: df["close"].pct_change().rolling(
            additional_parameters["vol_price_lookback"]
        ).corr(df["volume"]),
        deps=["close", "volume"],
    ),
    "percent_b": DerivedIndicator(
        fn=lambda df: (df["close"] - df["bbl_20_2_2"]) / (df["bbu_20_2_2"] - df["bbl_20_2_2"]),
        deps=["close", "bbu_20_2_2", "bbl_20_2_2"],
    ),
    "ema_50_slope": DerivedIndicator(
        fn=lambda df: (df["ema_50"] - df["ema_50"].shift(
            additional_parameters["ema_slope_lookback"]
        )) / df["ema_50"].shift(additional_parameters["ema_slope_lookback"]),
        deps=["ema_50"],
    ),
    "distance_from_ema_200": DerivedIndicator(
        fn=lambda df: (df["close"] - df["ema_200"]) / df["ema_200"],
        deps=["close", "ema_200"],
    ),
    "distance_from_ema_50": DerivedIndicator(
        fn=lambda df: (df["close"] - df["ema_50"]) / df["ema_50"],
        deps=["close", "ema_50"],
    ),
    "risk_adjusted_return": DerivedIndicator(
        fn=lambda df: df["roc_20"] / (df["atrr_14"] / df["close"]),
        deps=["roc_20", "atrr_14", "close"],
    ),
    "rvol": DerivedIndicator(
        fn=lambda df: df["volume"] / df["vol_sma_20"],
        deps=["volume", "vol_sma_20"],
    ),
    "atr_spike": DerivedIndicator(
        fn=lambda df: df["atrr_14"] / df["atrr_14"].rolling(20).mean(),
        deps=["atrr_14"],
    ),
    "momentum_3m": DerivedIndicator(
        fn=lambda df: (df["close"].shift(5) / df["close"].shift(65)) - 1,
        deps=["close"],
    ),
    "momentum_6m": DerivedIndicator(
        fn=lambda df: (df["close"].shift(5) / df["close"].shift(130)) - 1,
        deps=["close"],
    ),

    # ── Derived: Strategy 2 (new) ─────────────────────────────────────────────
    "adx_14_derived": DerivedIndicator(   # fallback via function if study fails
        fn=_compute_adx_14,
        deps=["high", "low", "close"],
    ),
    "mansfield_rs": DerivedIndicator(
        fn=_compute_mansfield_rs,
        deps=["close"],
        needs_benchmark=True,
    ),
    "nse_norm_momentum": DerivedIndicator(
        fn=_compute_nse_norm_momentum,
        deps=["close"],
    ),
    "sortino_ratio": DerivedIndicator(
        fn=_compute_sortino_ratio,
        deps=["close"],
    ),
    "scaled_turnover": DerivedIndicator(
        fn=_compute_scaled_turnover,
        deps=["close", "volume"],
    ),
    "log_price_vol_corr": DerivedIndicator(
        fn=_compute_log_price_vol_corr,
        deps=["close", "volume"],
    ),
    "momentum_12m": DerivedIndicator(
        fn=_compute_momentum_12m,
        deps=["close"],
    ),
    "quality_z_score": DerivedIndicator(
        fn=_compute_quality_z_score,
        deps=[],
    ),
}

# Study name → study object map (used by IndicatorsService for grouping)
STUDY_MAP: dict = {
    "ema_strategy": ema_strategy,
    "momentum_strategy": momentum_strategy,
    "derived_strategy": derived_strategy,
    "strategy2_adx_study": strategy2_adx_study,
}

# Ordered list of all patchable indicator names (for /indicators/patch default)
ALL_INDICATOR_NAMES: list = list(INDICATOR_REGISTRY.keys())
