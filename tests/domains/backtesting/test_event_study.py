from __future__ import annotations

from datetime import date, timedelta

from src.domains.backtesting.event_study import (
    evaluate_signal,
    stationary_interval,
    validation_gate,
    window_report,
)
from src.domains.strategies.positional_trend import signal_series


def _bars(count=110, *, volume=2_000_000):
    start = date(2022, 1, 1)
    days = [(start + timedelta(days=i)).isoformat() for i in range(count)]
    bars = [
        {"as_of_date": day, "open": 100, "high": 101, "low": 99, "close": 100, "volume": volume}
        for day in days
    ]
    bars[105].update(open=110, high=111, low=109, close=110)
    return days, bars


def test_event_uses_next_open_and_requires_complete_forward_window():
    days, bars = _bars(160)
    signal = signal_series(bars, days, "TEST")[0]
    by_day = {bar["as_of_date"]: bar for bar in bars}
    by_day[days[106]].update(open=112, high=113)
    event = evaluate_signal(signal, by_day, days, {day: i for i, day in enumerate(days)})
    assert event["status"] == "modeled_fill"
    assert event["entry_date"] == days[106]
    assert event["net_5"] == 100 / 112 - 1 - 0.005
    del by_day[days[108]]
    incomplete = evaluate_signal(signal, by_day, days, {day: i for i, day in enumerate(days)})
    assert "net_5" not in incomplete
    by_day[days[106]].update(open=114, high=115)
    skipped = evaluate_signal(signal, by_day, days, {day: i for i, day in enumerate(days)})
    assert skipped["status"] == "gap_skipped"


def test_block_bootstrap_keeps_nested_arms_together():
    days = [f"2022-01-{i:02d}" for i in range(1, 31)]
    events = [
        {"signal_date": day, "filtered": filtered, "net_20": 0.02}
        for day in days
        for filtered in (False, True)
    ]
    result = stationary_interval(events, days, 20, seed=17, replicates=200)
    assert result["ci95"] == [0.0, 0.0]
    assert result == stationary_interval(events, days, 20, seed=17, replicates=200)


def test_phase1_rejects_insufficient_validation_bootstrap_support():
    uncertainty = {"valid_replicates": 5000, "replicates": 5000, "ci95": [0.01, 0.03]}
    arm = {"complete_events": 30, "p90_mae": 0.1}
    horizon = {
        "strategy": arm,
        "baseline": arm,
        "mean_net_difference": 0.02,
        "uncertainty": uncertainty,
    }
    dev = {"horizons": {"20": horizon}}
    val = {
        "horizons": {"20": {**horizon, "uncertainty": {**uncertainty, "valid_replicates": 4000}}}
    }
    assert validation_gate(dev, val)["status"] == "inconclusive"
    assert validation_gate(dev, dev)["status"] == "advance_to_portfolio_simulation"


def test_empty_study_is_inconclusive_and_retains_bootstrap_metadata():
    empty = window_report([], [], seed=4)
    assert validation_gate(empty, empty)["status"] == "inconclusive"
    assert stationary_interval([], [], 20, seed=4)["replicates"] == 5000
