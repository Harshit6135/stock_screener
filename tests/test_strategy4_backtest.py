from __future__ import annotations

import sqlite3

from src.application import positional_trend_backtest as strategy4_backtest


def test_backtest_enters_and_exits_at_following_open_with_cash_and_fees(monkeypatch):
    days = ["2022-01-03", "2022-01-04", "2022-01-05"]
    bars = [
        {"as_of_date": days[0], "open": 100, "high": 101, "low": 99, "close": 100, "volume": 2_000_000},
        {"as_of_date": days[1], "open": 100, "high": 101, "low": 94, "close": 95, "volume": 2_000_000},
        {"as_of_date": days[2], "open": 90, "high": 91, "low": 89, "close": 90, "volume": 2_000_000},
    ]

    def features(_bars, _sessions, _symbol, _rules=None):
        return [
            {"symbol": "TEST", "signal_date": days[0], "close": 100, "adx14": 30,
             "adv30": 200_000_000, "initial_stop_anchor": 90, "filtered": True,
             "exit_signal": False},
            {"symbol": "TEST", "signal_date": days[1], "close": 95, "adx14": 30,
             "adv30": 200_000_000, "initial_stop_anchor": 90, "filtered": False,
             "exit_signal": True},
        ]

    monkeypatch.setattr(strategy4_backtest, "feature_series", features)
    policy = strategy4_backtest.Policy(initial_capital=1_000, max_positions=1,
                                       max_name_fraction=1)
    result = strategy4_backtest.simulate({"id": ("TEST", bars)}, days, policy=policy,
                                         end_date=days[-1])
    assert [fill["date"] for fill in result["fills"]] == days[1:]
    assert [fill["side"] for fill in result["fills"]] == ["BUY", "SELL"]
    assert result["fills"][0]["shares"] == 1
    assert result["trades"][0]["exit_signal_date"] == days[1]
    assert result["performance"]["final_equity"] == 989.525
    assert result["performance"]["open_positions"] == 0


def test_pyramid_add_sizes_as_independent_order_with_zero_prior_nominal_risk(monkeypatch):
    days = [f"2022-01-0{i}" for i in range(3, 8)]
    prices = [(100, 101, 99, 100), (100, 121, 99, 120),
              (122, 126, 120, 125), (125, 126, 89, 90), (85, 90, 84, 85)]
    bars = [{"as_of_date": day, "open": o, "high": h, "low": l, "close": c,
             "volume": 2_000_000}
            for day, (o, h, l, c) in zip(days, prices)]

    def features(_bars, _sessions, _symbol, _rules=None):
        return [
            {"symbol": "TEST", "signal_date": days[0], "close": 100, "adx14": 30,
             "adv30": 200_000_000, "initial_stop_anchor": 90, "filtered": True,
             "exit_signal": False},
            {"symbol": "TEST", "signal_date": days[1], "close": 120, "adx14": 20,
             "adv30": 200_000_000, "initial_stop_anchor": 110, "filtered": True,
             "exit_signal": False},
            {"symbol": "TEST", "signal_date": days[2], "close": 125, "adx14": 45,
             "adv30": 200_000_000, "initial_stop_anchor": 115, "filtered": True,
             "exit_signal": False},
            {"symbol": "TEST", "signal_date": days[3], "close": 90, "adx14": 15,
             "adv30": 200_000_000, "initial_stop_anchor": 100, "filtered": False,
             "exit_signal": True},
        ]

    monkeypatch.setattr(strategy4_backtest, "feature_series", features)
    base = strategy4_backtest.Policy(initial_capital=100_000, max_positions=1)
    on = strategy4_backtest.simulate({"id": ("TEST", bars)}, days,
                                     policy=strategy4_backtest.Policy(
                                         initial_capital=100_000, max_positions=1,
                                         enable_pyramiding=True), end_date=days[-1])
    off = strategy4_backtest.simulate({"id": ("TEST", bars)}, days,
                                      policy=base, end_date=days[-1])
    assert [fill["side"] for fill in on["fills"]] == ["BUY", "PYRAMID_ADD", "SELL"]
    assert on["fills"][1]["date"] == days[2]
    assert on["fills"][1]["shares"] == 83
    assert on["trades"][0]["pyramid_adds"] == 1
    assert on["trades"][0]["shares"] == 183
    assert on["fills"][1]["shares"] * (122 - 110) <= on["fills"][1]["equity_at_open"] * .01
    assert on["fills"][1]["order_fraction_of_equity"] <= .10
    assert on["fills"][1]["name_fraction_after"] > .10
    assert on["execution_skips"]["pyramid_prior_risk_not_zero"] == 1
    assert [fill["side"] for fill in off["fills"]] == ["BUY", "SELL"]


def test_new_candidate_and_pyramid_add_share_adx_ranking(monkeypatch):
    days = ["2022-01-03", "2022-01-04", "2022-01-05"]
    def bars(prices):
        return [{"as_of_date": day, "open": price, "high": price + 2,
                 "low": price - 2, "close": price, "volume": 2_000_000}
                for day, price in zip(days, prices)]

    def features(_bars, _sessions, symbol, _rules=None):
        if symbol == "A":
            return [
                {"symbol": "A", "signal_date": days[0], "close": 100, "adx14": 30,
                 "adv30": 200_000_000, "initial_stop_anchor": 90, "filtered": True,
                 "exit_signal": False},
                {"symbol": "A", "signal_date": days[1], "close": 120, "adx14": 35,
                 "adv30": 200_000_000, "initial_stop_anchor": 110, "filtered": True,
                 "exit_signal": False},
            ]
        return [{"symbol": "B", "signal_date": days[1], "close": 100, "adx14": 40,
                 "adv30": 200_000_000, "initial_stop_anchor": 90, "filtered": True,
                 "exit_signal": False}]

    monkeypatch.setattr(strategy4_backtest, "feature_series", features)
    result = strategy4_backtest.simulate(
        {"a": ("A", bars([100, 100, 122])),
         "b": ("B", bars([100, 100, 100]))}, days,
        policy=strategy4_backtest.Policy(initial_capital=100_000, max_positions=2,
                                         enable_pyramiding=True), end_date=days[-1])
    assert [(fill["date"], fill["symbol"], fill["side"]) for fill in result["fills"]] == [
        (days[1], "A", "BUY"), (days[2], "B", "BUY"), (days[2], "A", "PYRAMID_ADD")]


def test_market_cap_loader_includes_both_exchanges_and_excludes_below_threshold(tmp_path):
    database = tmp_path / "market.db"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE reference_instruments(instrument_id TEXT, symbol TEXT, exchange TEXT, observed_on TEXT);
        CREATE TABLE universe_membership(instrument_id TEXT, isin TEXT, exchange TEXT,
                                         last_market_cap REAL, snapshot_date TEXT);
        CREATE TABLE market_bars(instrument_id TEXT, as_of_date TEXT, open REAL, high REAL,
                                 low REAL, close REAL, volume REAL);
        INSERT INTO reference_instruments VALUES ('a','A','NSE','2026-09-19'),
            ('b','B','BSE','2026-09-19'), ('c','C','NSE','2026-09-19'),
            ('index','NIFTY 500','NSE','2026-09-19');
        INSERT INTO universe_membership VALUES ('a','isin-a','NSE',6000000000,'2026-09-19'),
            ('b','isin-b','BSE',5000000000,'2026-09-19'),
            ('c','isin-c','NSE',4999999999,'2026-09-19');
        INSERT INTO market_bars VALUES ('a','2022-01-03',100,101,99,100,1000000),
            ('b','2022-01-03',100,101,99,100,1000000),
            ('index','2022-01-03',100,101,99,100,0);
    """)
    connection.commit()
    connection.close()
    histories, sessions, coverage = strategy4_backtest.load_market_cap_universe(
        database, end_date="2026-09-28")
    assert set(histories) == {"a", "b"}
    assert sessions == ["2022-01-03"]
    assert coverage["members_by_exchange"] == {"NSE": 1, "BSE": 1}
    assert coverage["membership_snapshot_dates"] == ["2026-09-19"]
