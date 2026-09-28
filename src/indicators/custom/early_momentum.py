"""Raw, point-in-time inputs for the isolated Strategy 3 event study."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd


def early_momentum_feature_series(
    bars: Sequence[dict[str, Any]], benchmark: Sequence[dict[str, Any]]
) -> dict[str, dict[str, object]]:
    """Calculate Strategy 3 inputs without cross-sectional ranking or fills.

    Each output only uses data available at that session's completed close.
    The 317-bar gate supplies one price before the first beta return.
    """
    if len(bars) < 317 or len(benchmark) < 317:
        return {}
    stock = pd.DataFrame(bars).sort_values("as_of_date").drop_duplicates("as_of_date")
    market = pd.DataFrame(benchmark).sort_values("as_of_date").drop_duplicates("as_of_date")
    if stock.empty or market.empty:
        return {}
    stock["as_of_date"] = stock["as_of_date"].astype(str)
    market["as_of_date"] = market["as_of_date"].astype(str)
    stock = stock.set_index("as_of_date")
    market_close = pd.to_numeric(market.set_index("as_of_date")["close"], errors="coerce")
    frame = stock.reindex(market_close.index)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    close, high, low, volume = (frame[key] for key in ("close", "high", "low", "volume"))
    valid_bar = np.isfinite(frame[["open", "high", "low", "close", "volume"]]).all(axis=1)
    valid_bar &= (frame[["open", "high", "low", "close", "volume"]] > 0).all(axis=1)
    valid_bar &= (high >= frame[["open", "close", "low"]].max(axis=1))
    valid_bar &= (low <= frame[["open", "close"]].min(axis=1))
    stock_return = np.log(close / close.shift(1))
    market_return = np.log(market_close / market_close.shift(1))
    middle = close.rolling(20, min_periods=20).mean()
    deviation = close.rolling(20, min_periods=20).std(ddof=0)
    upper = middle + 2 * deviation
    lower = middle - 2 * deviation
    bbw = (upper - lower) / middle.replace(0, np.nan)
    bbw_percentile_126 = pd.Series(np.nan, index=frame.index, dtype=float)
    for position in range(126, len(frame)):
        prior_widths = bbw.iloc[position - 126 : position].to_numpy(dtype=float)
        current_width = float(bbw.iloc[position])
        if np.isfinite(current_width) and np.isfinite(prior_widths).all():
            bbw_percentile_126.iloc[position] = (
                np.count_nonzero(prior_widths <= current_width) / 126
            )
    bbw_prior10_min_percentile = bbw_percentile_126.shift(1).rolling(
        10, min_periods=10
    ).min()
    bbw_prior_percentile_126 = bbw_percentile_126.shift(1)
    sma50 = close.rolling(50, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    benchmark_sma200 = market_close.rolling(200, min_periods=200).mean()
    ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    # Wilder's seed is the mean of 14 valid true ranges, not the first TR.
    atr14 = pd.Series(np.nan, index=frame.index)
    seed: list[float] = []
    last_atr = None
    for position in range(len(frame)):
        if position == 0 or not valid_bar.iloc[position] or not valid_bar.iloc[position - 1]:
            seed, last_atr = [], None
            continue
        tr = float(true_range.iloc[position])
        if last_atr is None:
            seed.append(tr)
            if len(seed) == 14:
                last_atr = sum(seed) / 14
        else:
            last_atr = (13 * last_atr + tr) / 14
        if last_atr is not None:
            atr14.iloc[position] = last_atr
    prior50_volume = volume.shift(1).rolling(50, min_periods=50).mean()
    prior20_volume = volume.shift(1).rolling(20, min_periods=20).mean()
    prior252_volume = volume.shift(1).rolling(252, min_periods=252).mean()
    # OHLCV turnover proxy, evaluated before the signal bar.
    adv30_value = (close * volume).shift(1).rolling(30, min_periods=30).mean()
    prior252_high = close.shift(1).rolling(252, min_periods=252).max()
    prior20_high = high.shift(1).rolling(20, min_periods=20).max()
    close_location = ((close - low) / (high - low).replace(0, np.nan)).where(high != low, 0.5)
    daily_move_atr = (close - previous_close) / atr14.shift(1)
    momentum_63_skip5 = np.log(close.shift(5) / close.shift(68))
    output: dict[str, dict[str, object]] = {}
    for index in range(316, len(frame)):
        # The analytical samples are rejected if either instrument or benchmark
        # misses a session; reindexing to benchmark dates makes this explicit.
        if not valid_bar.iloc[index - 316 : index + 1].all():
            continue
        beta_stock = stock_return.iloc[index - 315 : index - 63].to_numpy(dtype=float)
        beta_market = market_return.iloc[index - 315 : index - 63].to_numpy(dtype=float)
        signal_stock = stock_return.iloc[index - 62 : index + 1].to_numpy(dtype=float)
        signal_market = market_return.iloc[index - 62 : index + 1].to_numpy(dtype=float)
        if not (
            len(beta_stock) == 252
            and len(signal_stock) == 63
            and np.isfinite(beta_stock).all()
            and np.isfinite(beta_market).all()
            and np.isfinite(signal_stock).all()
            and np.isfinite(signal_market).all()
        ):
            continue
        design = np.column_stack((np.ones(252), beta_market))
        _alpha, beta = np.linalg.lstsq(design, beta_stock, rcond=None)[0]
        residuals = signal_stock - beta * signal_market
        residual_std = float(np.std(residuals, ddof=1))
        prior_volumes = volume.iloc[index - 50 : index].to_numpy(dtype=float)
        required = (
            middle.iloc[index], upper.iloc[index], upper.iloc[index - 1], bbw.iloc[index],
            sma50.iloc[index], sma200.iloc[index], ema20.iloc[index], atr14.iloc[index],
            prior50_volume.iloc[index], bbw_percentile_126.iloc[index],
            bbw_prior10_min_percentile.iloc[index], bbw_prior_percentile_126.iloc[index],
            prior20_volume.iloc[index], prior252_volume.iloc[index], adv30_value.iloc[index],
            lower.iloc[index], prior20_high.iloc[index],
            prior20_high.iloc[index - 1], close_location.iloc[index],
            daily_move_atr.iloc[index], momentum_63_skip5.iloc[index],
            market_close.iloc[index], benchmark_sma200.iloc[index],
        )
        if (
            residual_std <= 0
            or not np.isfinite(residual_std)
            or not np.isfinite(prior_volumes).all()
            or (prior_volumes <= 0).any()
            or not all(math.isfinite(float(value)) for value in required)
            or float(atr14.iloc[index]) <= 0
        ):
            continue
        residual_score = float(np.sum(residuals)) / residual_std
        bbw_percentile = float(bbw_percentile_126.iloc[index])
        relative_volume = float(volume.iloc[index] / prior50_volume.iloc[index])
        extension = float((close.iloc[index] - ema20.iloc[index]) / atr14.iloc[index])
        trend_ok = bool(close.iloc[index] > sma50.iloc[index] > sma200.iloc[index])
        squeeze_ok = bbw_percentile <= 0.25
        cross_ok = bool(close.iloc[index - 1] <= upper.iloc[index - 1] and close.iloc[index] > upper.iloc[index])
        volume_ok = relative_volume > 1.5
        extension_ok = extension < 2.5
        prior20_high_cross_ok = bool(
            close.iloc[index] > prior20_high.iloc[index]
            and close.iloc[index - 1] <= prior20_high.iloc[index - 1]
        )
        naive_52w_high_cross_ok = bool(
            close.iloc[index] > prior252_high.iloc[index]
            and close.iloc[index - 1] <= prior252_high.iloc[index - 1]
        )
        benchmark_regime_ok = bool(market_close.iloc[index] > benchmark_sma200.iloc[index])
        reasons = [
            name for name, passed in (
                ("trend", trend_ok), ("squeeze", squeeze_ok), ("bollinger_cross", cross_ok),
                ("relative_volume", volume_ok), ("atr_extension", extension_ok),
            ) if not passed
        ]
        day = str(frame.index[index])
        output[day] = {
            "close": float(close.iloc[index]), "open": float(frame["open"].iloc[index]),
            "high": float(high.iloc[index]), "low": float(low.iloc[index]),
            "volume": float(volume.iloc[index]), "residual_score": residual_score,
            "prior_252_close_high": float(prior252_high.iloc[index]),
            "naive_52w_high_cross_ok": naive_52w_high_cross_ok,
            "sma50": float(sma50.iloc[index]), "sma200": float(sma200.iloc[index]),
            "upper_bb20_2": float(upper.iloc[index]), "middle_bb20_2": float(middle.iloc[index]),
            "lower_bb20_2": float(lower.iloc[index]),
            "bbw20_2": float(bbw.iloc[index]), "bbw_percentile_126": bbw_percentile,
            "bbw_prior_percentile_126": float(bbw_prior_percentile_126.iloc[index]),
            "bbw_prior10_min_percentile": float(bbw_prior10_min_percentile.iloc[index]),
            "prior20_volume": float(prior20_volume.iloc[index]),
            "prior252_volume": float(prior252_volume.iloc[index]),
            "adv30_value": float(adv30_value.iloc[index]),
            "prior20_high": float(prior20_high.iloc[index]),
            "prior20_high_cross_ok": prior20_high_cross_ok,
            "close_location": float(close_location.iloc[index]),
            "daily_move_atr": float(daily_move_atr.iloc[index]),
            "momentum_63_skip5": float(momentum_63_skip5.iloc[index]),
            "benchmark_regime_ok": benchmark_regime_ok,
            "relative_volume_50": relative_volume, "ema20": float(ema20.iloc[index]),
            "atr14_wilder": float(atr14.iloc[index]), "extension_atr": extension,
            "trend_ok": trend_ok, "squeeze_ok": squeeze_ok, "cross_ok": cross_ok,
            "volume_ok": volume_ok, "extension_ok": extension_ok,
            "pre_rank_signal_ok": not reasons, "signal_reason_codes": reasons,
        }
    return output


def early_momentum_features(
    bars: Sequence[dict[str, Any]], benchmark: Sequence[dict[str, Any]]
) -> dict[str, object] | None:
    """Return final completed-session input for StrategyRuntime compatibility."""
    series = early_momentum_feature_series(bars, benchmark)
    return next(reversed(series.values())) if series else None
