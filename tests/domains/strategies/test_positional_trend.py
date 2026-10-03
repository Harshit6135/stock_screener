from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.domains.strategies.positional_trend import feature_series, signal_series


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
