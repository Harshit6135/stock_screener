from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from src.domains.strategies import positional_trend
from src.domains.strategies.positional_trend import feature_series, signal_series
from src.domains.strategies.positional_trend_backtest import Policy, simulate


@pytest.mark.parametrize("period", [1, 7, 30, 100])
def test_exact_adtv_matches_original_window_sums_bit_for_bit(period):
    rng = random.Random(741)
    values = [float(rng.randrange(0, 10**9)) for _ in range(250)]
    prefix = positional_trend._exact_value_prefix(values)
    assert prefix is not None
    for i in range(period, len(values)):
        expected = sum(values[i - period:i]) / period
        actual = (prefix[i] - prefix[i - period]) / period
        assert actual.hex() == expected.hex()
    boundary = positional_trend._exact_value_prefix([float(2**53 - 1), 1.0, 0.0])
    assert boundary == [0.0, float(2**53 - 1), float(2**53), float(2**53)]


@pytest.mark.parametrize("values", [
    [0.1, 0.2, 0.3], [-1.0, 2.0], [math.inf], [math.nan],
    [float(2**53), 1.0], [float(2**53 + 2)],
])
def test_adtv_falls_back_when_exact_prefix_arithmetic_cannot_be_certified(values):
    assert positional_trend._exact_value_prefix(values) is None


@pytest.mark.parametrize("fractional", [False, True])
def test_adtv_preserves_threshold_edges_and_complete_replay(tmp_path, monkeypatch, fractional):
    days, bars = _fixture()
    if fractional:
        bars = [{**bar, "open": bar["open"] + 0.1, "high": bar["high"] + 0.1,
                 "low": bar["low"] + 0.1, "close": bar["close"] + 0.1, "volume": 3}
                for bar in bars]
    prior = sum(float(bar["close"]) * float(bar["volume"]) for bar in bars[70:100]) / 30
    thresholds = [math.nextafter(prior, -math.inf), prior, math.nextafter(prior, math.inf)]
    optimized = [feature_series(bars, days, "A", {"minimum_adtv": threshold})
                 for threshold in thresholds]
    replay = simulate(
        {"a": ("A", bars)}, days, policy=Policy(), start_date=days[0], end_date=days[-1],
        rules={"minimum_adtv": 0, "adx_minimum": 0},
    )
    monkeypatch.setattr(positional_trend, "_exact_value_prefix", lambda _: None)
    baseline = [feature_series(bars, days, "A", {"minimum_adtv": threshold})
                for threshold in thresholds]
    assert optimized == baseline
    assert [rows[80]["first_cross"] for rows in optimized] == [True, False, False]
    assert simulate(
        {"a": ("A", bars)}, days, policy=Policy(), start_date=days[0], end_date=days[-1],
        rules={"minimum_adtv": 0, "adx_minimum": 0},
    ) == replay


def _bars(count=110, *, volume=2_000_000):
    start = date(2022, 1, 1)
    days = [(start + timedelta(days=i)).isoformat() for i in range(count)]
    bars = [
        {"as_of_date": day, "open": 100, "high": 101, "low": 99, "close": 100, "volume": volume}
        for day in days
    ]
    bars[105].update(open=110, high=111, low=109, close=110)
    return days, bars


def test_first_cross_uses_prior_bars_and_does_not_look_ahead():
    days, bars = _bars()
    original = signal_series(bars[:106], days[:106], "TEST")
    extended = signal_series(bars, days, "TEST")
    assert [item["signal_date"] for item in original] == [days[105]]
    assert original == [item for item in extended if item["signal_date"] <= days[105]]
    assert original[0]["adv30"] == 200_000_000
    # The signal bar's enormous volume cannot rescue a failing prior ADTV gate.
    thin = [dict(bar, volume=100) for bar in bars]
    thin[105]["volume"] = 10**9
    assert signal_series(thin, days, "TEST") == []


def test_missing_stock_bar_is_skipped_without_resetting_warmup():
    days, bars = _bars()
    without_day = [bar for bar in bars if bar["as_of_date"] != days[100]]
    assert [row["signal_date"] for row in signal_series(without_day, days, "TEST")] == [days[105]]


def _fixture():
    days = [(date(2022, 1, 1) + timedelta(days=i)).isoformat() for i in range(125)]
    bars = [
        {"as_of_date": day, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 2_000_000}
        for day in days
    ]
    bars[100].update(open=110, high=111, low=109, close=110)
    return days, bars


def test_fixed_fixture_wilder_atr_adx_and_supertrend_flip():
    days, bars = _fixture()
    rows = {row["signal_date"]: row for row in feature_series(bars, days, "A")}
    assert rows[days[99]]["atr10"] == 2
    assert rows[days[99]]["supertrend"] == 94
    assert rows[days[99]]["supertrend_bullish"]
    assert rows[days[100]]["atr10"] == pytest.approx(2.9)
    assert rows[days[100]]["adx14"] == pytest.approx(100 / 14)
    assert rows[days[100]]["supertrend"] == pytest.approx(101.3)
    assert rows[days[100]]["upper50"] == 101
    assert rows[days[100]]["lower20"] == 99
    assert rows[days[100]]["initial_stop_anchor"] == pytest.approx(101.3)
    assert rows[days[101]]["atr10"] == pytest.approx(3.71)
    assert not rows[days[101]]["supertrend_bullish"]
    assert rows[days[101]]["supertrend"] == pytest.approx(111.13)
    assert rows[days[101]]["exit_signal"]


def test_warmup_liquidity_and_adx_boundaries():
    days, bars = _fixture()
    # Exactly 100 prior valid bars suffice. The active warm-up override is honored.
    signal = feature_series(bars, days, "A")[-25]
    assert signal["signal_date"] == days[100]
    assert signal["first_cross"]
    assert not feature_series(bars, days, "A", {"required_sessions": 101})[-25]["first_cross"]
    assert not feature_series(bars, days, "A", {"adx_minimum": signal["adx14"]})[-25]["filtered"]
    assert feature_series(bars, days, "A", {"adx_minimum": 0})[-25]["filtered"]
    thin = [{**bar, "volume": 1_000_000} for bar in bars]
    assert not feature_series(thin, days, "A")[-25]["first_cross"]


def test_donchian_equality_and_supertrend_equality_do_not_trigger():
    days, bars = _fixture()
    bars[100].update(open=101, high=102, low=100, close=101)
    row = feature_series(bars, days, "A")[-25]
    assert row["upper50"] == 101
    assert not row["first_cross"]
    # First finite ATR is 2 and the carried lower band is exactly 94.
    bars[100].update(open=100, high=101, low=94, close=94)
    row = feature_series(bars, days, "A")[-25]
    assert row["supertrend"] == 94
    assert row["supertrend_bullish"]
    # Equality to Supertrend does not flip; close below the Donchian low exits.
    assert row["exit_signal"]
