"""Boundary and fixed-fixture verification against the Strategy 4 v4 specification."""

from datetime import date, timedelta

import pytest

from src.application import positional_trend_backtest as replay
from src.application.positional_trend import feature_series
from tools.strategy4_event_study import stationary_interval, validation_gate, window_report


def _fixture():
    days = [(date(2022, 1, 1) + timedelta(days=i)).isoformat() for i in range(125)]
    bars = [{"as_of_date": day, "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": 2_000_000} for day in days]
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


@pytest.mark.parametrize("opening,expected_buy", [(103, True), (103.01, False), (90, False), (89, False)])
def test_gap_and_stop_boundary_use_following_open(monkeypatch, opening, expected_buy):
    days = ["2022-01-03", "2022-01-04"]
    bars = [{"as_of_date": day, "open": price, "high": max(price, 100) + 1,
             "low": min(price, 100) - 1, "close": 100, "volume": 2_000_000}
            for day, price in zip(days, [100, opening])]
    signal = {"symbol": "A", "signal_date": days[0], "close": 100,
              "adx14": 30, "adv30": 200_000_000, "initial_stop_anchor": 90,
              "filtered": True, "exit_signal": False}
    monkeypatch.setattr(replay, "feature_series", lambda *args: [signal])
    result = replay.simulate({"a": ("A", bars)}, days, policy=replay.Policy(),
                             start_date=days[0], end_date=days[-1])
    assert bool(result["fills"]) is expected_buy
    if expected_buy:
        assert result["fills"][0]["date"] == days[1]
        assert result["fills"][0]["price"] == opening


def test_exit_precedes_ranked_entries_and_ranking_has_three_ties(monkeypatch):
    days = ["2022-01-03", "2022-01-04", "2022-01-05"]
    symbols = ("HELD", "C", "B", "A", "D")
    base = {"close": 100, "adx14": 30, "adv30": 200_000_000,
            "initial_stop_anchor": 90, "filtered": True, "exit_signal": False}
    signals = {"HELD": [{**base, "symbol": "HELD", "signal_date": days[0]},
                        {**base, "symbol": "HELD", "signal_date": days[1],
                         "filtered": False, "exit_signal": True}]}
    for symbol in symbols[1:]:
        signals[symbol] = [{**base, "symbol": symbol, "signal_date": days[1]}]
    signals["B"][0]["adv30"] *= 2
    signals["D"][0]["adx14"] += 1
    bars = [{"as_of_date": day, "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": 2_000_000} for day in days]
    monkeypatch.setattr(replay, "feature_series", lambda history, sessions, symbol, rules: signals[symbol])
    result = replay.simulate({symbol: (symbol, bars) for symbol in symbols}, days,
                             policy=replay.Policy(max_positions=4), start_date=days[0], end_date=days[-1])
    last = [fill for fill in result["fills"] if fill["date"] == days[-1]]
    assert [(fill["side"], fill["symbol"]) for fill in last] == [
        ("SELL", "HELD"), ("BUY", "D"), ("BUY", "B"), ("BUY", "A"), ("BUY", "C")]


def test_phase1_rejects_insufficient_validation_bootstrap_support():
    uncertainty = {"valid_replicates": 5000, "replicates": 5000, "ci95": [.01, .03]}
    arm = {"complete_events": 30, "p90_mae": .1}
    horizon = {"strategy": arm, "baseline": arm, "mean_net_difference": .02,
               "uncertainty": uncertainty}
    dev = {"horizons": {"20": horizon}}
    val = {"horizons": {"20": {**horizon, "uncertainty": {**uncertainty, "valid_replicates": 4000}}}}
    assert validation_gate(dev, val)["status"] == "inconclusive"
    assert validation_gate(dev, dev)["status"] == "advance_to_portfolio_simulation"


def test_empty_study_is_inconclusive_and_retains_bootstrap_metadata():
    empty = window_report([], [], seed=4)
    assert validation_gate(empty, empty)["status"] == "inconclusive"
    assert stationary_interval([], [], 20, seed=4)["replicates"] == 5000
