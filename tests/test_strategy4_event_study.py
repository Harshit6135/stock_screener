from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from src.application.positional_trend import signal_series
from tools.strategy4_event_study import evaluate_signal, load_data, stationary_interval


def test_constituent_loader_includes_be_only_when_requested(tmp_path):
    database = tmp_path / "bars.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE reference_instruments (instrument_id, isin, symbol, observed_on, exchange);"
            "CREATE TABLE market_bars (instrument_id, as_of_date, open, high, low, close, volume);"
            "INSERT INTO reference_instruments VALUES ('a','ISINA','A','2026-01-01','NSE'),"
            "('b','ISINB','B','2026-01-01','BSE');"
            "INSERT INTO market_bars VALUES ('a','2022-01-03',100,101,99,100,1000),"
            "('b','2022-01-03',100,101,99,100,1000);"
        )
    constituents = tmp_path / "members.csv"
    constituents.write_text("Symbol,Series,ISIN Code\nA,EQ,ISINA\nB,BE,ISINB\n", encoding="utf-8")
    eq, _, eq_coverage = load_data(database, constituents, end_date="2022-01-03")
    both, _, coverage = load_data(database, constituents, end_date="2022-01-03", include_be=True)
    assert set(eq) == {"a"}
    assert set(both) == {"a", "b"}
    assert eq_coverage["included_series"] == ["EQ"]
    assert coverage["constituent_eq_count"] == 1
    assert coverage["included_member_count"] == 2
    assert coverage["bar_count"] == 2
    assert coverage["matched_members_by_exchange"] == {"NSE": 1, "BSE": 1}


def _bars(count=110, *, volume=2_000_000):
    start = date(2022, 1, 1)
    days = [(start + timedelta(days=i)).isoformat() for i in range(count)]
    bars = [{"as_of_date": day, "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": volume}
            for day in days]
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


def test_event_uses_next_open_and_requires_complete_forward_window():
    days, bars = _bars(160)
    signal = signal_series(bars, days, "TEST")[0]
    by_day = {bar["as_of_date"]: bar for bar in bars}
    by_day[days[106]].update(open=112, high=113)
    event = evaluate_signal(signal, by_day, days, {day: i for i, day in enumerate(days)})
    assert event["status"] == "modeled_fill"
    assert event["entry_date"] == days[106]
    assert event["net_5"] == 100 / 112 - 1 - .005
    del by_day[days[108]]
    incomplete = evaluate_signal(signal, by_day, days, {day: i for i, day in enumerate(days)})
    assert "net_5" not in incomplete
    by_day[days[106]].update(open=114, high=115)
    skipped = evaluate_signal(signal, by_day, days, {day: i for i, day in enumerate(days)})
    assert skipped["status"] == "gap_skipped"


def test_block_bootstrap_keeps_nested_arms_together():
    days = [f"2022-01-{i:02d}" for i in range(1, 31)]
    events = [{"signal_date": day, "filtered": filtered, "net_20": .02}
              for day in days for filtered in (False, True)]
    result = stationary_interval(events, days, 20, seed=17, replicates=200)
    assert result["ci95"] == [0.0, 0.0]
    assert result == stationary_interval(events, days, 20, seed=17, replicates=200)
