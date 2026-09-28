"""Strategy 4 point-in-time signal calculation on daily OHLCV bars."""

from __future__ import annotations

import math
from collections import deque


def valid_bar(bar: dict) -> bool:
    try:
        o, h, l, c, v = (float(bar[key]) for key in ("open", "high", "low", "close", "volume"))
    except (KeyError, TypeError, ValueError):
        return False
    return all(map(math.isfinite, (o, h, l, c, v))) and 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0


_DEFAULT_RULES = {
    "donchian_entry_period": 50, "donchian_exit_period": 20,
    "adx_period": 14, "adx_minimum": 25, "atr_period": 10,
    "supertrend_multiplier": 3, "adtv_period": 30, "minimum_adtv": 100_000_000,
    "required_sessions": 100,
}


def _segment_features(bars: list[dict], symbol: str, rules: dict | None = None) -> list[dict]:
    """Wilder ATR/ADX, TA-Lib-style bullish Supertrend seed and current-band flips."""
    rules = {**_DEFAULT_RULES, **(rules or {})}
    entry_period = int(rules["donchian_entry_period"])
    exit_period = int(rules["donchian_exit_period"])
    adx_period = int(rules["adx_period"])
    atr_period = int(rules["atr_period"])
    adtv_period = int(rules["adtv_period"])
    adx_minimum = float(rules["adx_minimum"])
    supertrend_multiplier = float(rules["supertrend_multiplier"])
    minimum_adtv = float(rules["minimum_adtv"])
    required_sessions = int(rules["required_sessions"])
    n = len(bars)
    if n <= max(entry_period, exit_period, 2 * adx_period - 1, atr_period, adtv_period):
        return []
    high = [float(b["high"]) for b in bars]
    low = [float(b["low"]) for b in bars]
    close = [float(b["close"]) for b in bars]
    value = [close[i] * float(bars[i]["volume"]) for i in range(n)]
    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        up, down = high[i] - high[i - 1], low[i - 1] - low[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0

    atr = [math.nan] * n
    atr_adx = [math.nan] * n
    adx = [math.nan] * n
    st = [math.nan] * n
    bullish = [False] * n
    upper = lower = 0.0
    dx = [math.nan] * n
    sm_plus = sm_minus = 0.0
    for i in range(1, n):
        if i == atr_period:
            atr[i] = sum(tr[1:atr_period + 1]) / atr_period
        elif i > atr_period:
            atr[i] = (atr[i - 1] * (atr_period - 1) + tr[i]) / atr_period
        if i == adx_period:
            atr_adx[i] = sum(tr[1:adx_period + 1]) / adx_period
            sm_plus = sum(plus_dm[1:adx_period + 1]) / adx_period
            sm_minus = sum(minus_dm[1:adx_period + 1]) / adx_period
        elif i > adx_period:
            atr_adx[i] = (atr_adx[i - 1] * (adx_period - 1) + tr[i]) / adx_period
            sm_plus = (sm_plus * (adx_period - 1) + plus_dm[i]) / adx_period
            sm_minus = (sm_minus * (adx_period - 1) + minus_dm[i]) / adx_period
        if i >= adx_period:
            denominator = sm_plus + sm_minus
            dx[i] = 100 * abs(sm_plus - sm_minus) / denominator if denominator else 0.0
        adx_seed = 2 * adx_period - 1
        if i == adx_seed:
            adx[i] = sum(dx[adx_period:adx_seed + 1]) / adx_period
        elif i > adx_seed:
            adx[i] = (adx[i - 1] * (adx_period - 1) + dx[i]) / adx_period
        if i >= atr_period:
            mid = (high[i] + low[i]) / 2
            basic_upper = mid + supertrend_multiplier * atr[i]
            basic_lower = mid - supertrend_multiplier * atr[i]
            if i == atr_period:
                upper, lower = basic_upper, basic_lower
                bullish[i] = True
            else:
                upper = basic_upper if basic_upper < upper or close[i - 1] > upper else upper
                lower = basic_lower if basic_lower > lower or close[i - 1] < lower else lower
                bullish[i] = bullish[i - 1]
                if bullish[i - 1] and close[i] < lower:
                    bullish[i] = False
                elif not bullish[i - 1] and close[i] > upper:
                    bullish[i] = True
            st[i] = lower if bullish[i] else upper

    # Both rolling bands exclude the current bar. A first cross needs yesterday's band too.
    upper_entry = [math.nan] * n
    lower_exit = [math.nan] * n
    hi_queue: deque[int] = deque()
    lo_queue: deque[int] = deque()
    for i in range(n):
        previous = i - 1
        if previous >= 0:
            while hi_queue and high[hi_queue[-1]] <= high[previous]:
                hi_queue.pop()
            hi_queue.append(previous)
            while lo_queue and low[lo_queue[-1]] >= low[previous]:
                lo_queue.pop()
            lo_queue.append(previous)
        while hi_queue and hi_queue[0] < i - entry_period:
            hi_queue.popleft()
        while lo_queue and lo_queue[0] < i - exit_period:
            lo_queue.popleft()
        if i >= entry_period:
            upper_entry[i] = high[hi_queue[0]]
        if i >= exit_period:
            lower_exit[i] = low[lo_queue[0]]

    features = []
    feature_start = max(20, exit_period, atr_period)
    for i in range(feature_start, n):
        adtv = sum(value[i - adtv_period:i]) / adtv_period if i >= adtv_period else math.nan
        first_cross = (i >= max(required_sessions, entry_period + 1)
                       and close[i - 1] <= upper_entry[i - 1]
                       and close[i] > upper_entry[i] and adtv > minimum_adtv)
        filtered = first_cross and adx[i] > adx_minimum and bullish[i] and close[i] > st[i]
        features.append({"symbol": symbol, "signal_date": str(bars[i]["as_of_date"]),
                         "close": close[i], "adx14": adx[i] if math.isfinite(adx[i]) else None,
                         "upper50": upper_entry[i] if math.isfinite(upper_entry[i]) else None,
                         "atr10": atr[i], "supertrend_bullish": bullish[i],
                         "supertrend": st[i], "lower20": lower_exit[i],
                         "initial_stop_anchor": max(st[i], lower_exit[i]),
                         "adv30": adtv if math.isfinite(adtv) else None,
                         "first_cross": bool(first_cross), "filtered": bool(filtered),
                         "exit_signal": bool(close[i] < st[i] or close[i] < lower_exit[i])})
    return features


def feature_series(bars: list[dict], sessions: list[str], symbol: str,
                   rules: dict | None = None) -> list[dict]:
    """Skip absent stock sessions; reset warm-up only after an invalid stored bar."""
    by_day = {str(bar["as_of_date"]): bar for bar in bars}
    result: list[dict] = []
    segment: list[dict] = []
    for day in sessions:
        bar = by_day.get(day)
        if bar is None:
            # Treat a stock-specific non-session (or absent record) like a holiday.
            # Indicators advance on available valid bars rather than resetting.
            continue
        if not valid_bar(bar):
            if segment:
                result.extend(_segment_features(segment, symbol, rules))
                segment = []
        else:
            segment.append(bar)
    if segment:
        result.extend(_segment_features(segment, symbol, rules))
    return result


def signal_series(bars: list[dict], sessions: list[str], symbol: str) -> list[dict]:
    return [item for item in feature_series(bars, sessions, symbol) if item["first_cross"]]
