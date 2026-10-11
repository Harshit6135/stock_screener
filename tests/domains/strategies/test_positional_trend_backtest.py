from __future__ import annotations

import pytest

from src.domains.strategies import positional_trend_backtest as replay
from src.domains.strategies import positional_trend_backtest as positional_trend_backtest


def replay_fixture(monkeypatch, *, missing_open=False, extra_price=90):
    from src.domains.strategies import positional_trend_backtest as replay

    days = ["2026-06-04", "2026-06-05", "2026-06-08", "2026-06-09"]
    prices = [100, 100, extra_price, 200]
    rows = [
        {
            "as_of_date": day,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 100,
            "snapshot_id": f"price-{day}",
        }
        for day, price in zip(days, prices)
    ]
    if missing_open:
        rows = [row for row in rows if row["as_of_date"] != days[2]]

    def features(_history, _sessions, symbol, _rules):
        assert all(row["as_of_date"] <= days[1] for row in _history)
        return [
            {
                "symbol": symbol,
                "signal_date": days[0],
                "close": 100,
                "adx14": 30,
                "adv30": 200_000_000,
                "initial_stop_anchor": 90,
                "filtered": True,
                "exit_signal": False,
            }
        ]

    monkeypatch.setattr(replay, "feature_series", features)
    membership = {
        day: {
            "snapshot_id": "before" if day == days[0] else "after",
            "symbols": ["TEST"] if day == days[0] else [],
        }
        for day in days
    }
    # The purchase opens on Friday using Thursday's signal; membership removal
    # is assessed after Friday's daily analysis. Preserve Friday entry for this
    # fixture by reporting Friday membership until the close decision explicitly.
    membership[days[1]]["symbols"] = ["TEST"]
    return replay, days, rows, membership


def test_universe_exit_uses_next_observed_session_and_reports_provenance(monkeypatch):
    replay, days, rows, membership = replay_fixture(monkeypatch)
    # Include a Thursday signal, Friday entry, Monday removal and Tuesday exit.
    membership[days[2]]["symbols"] = []
    monkeypatch.setattr(
        replay,
        "feature_series",
        lambda *_: [
            {
                "symbol": "TEST",
                "signal_date": days[0],
                "close": 100,
                "adx14": 30,
                "adv30": 200_000_000,
                "initial_stop_anchor": 90,
                "filtered": True,
                "exit_signal": False,
            }
        ],
    )
    result = replay.simulate(
        {"share": ("TEST", rows)},
        days,
        policy=replay.Policy(initial_capital=10_000),
        start_date=days[0],
        end_date=days[-1],
        membership_by_day=membership,
    )
    sell = result["fills"][-1]
    assert sell["date"] == days[3]
    assert sell["price"] == 200
    assert sell["decision_date"] == days[2]
    assert sell["target_execution_session"] == days[3]
    assert sell["exit_reason"] == "universe_exit"
    assert sell["universe_snapshot_id"] == "after"
    assert sell["price_source"] == f"price-{days[3]}"
    assert sell["fill_status"] == "FILLED"


def test_extra_exit_session_does_not_change_prior_valuation_or_allow_entries(monkeypatch):
    replay, days, rows, membership = replay_fixture(monkeypatch)

    # A daily exit decision on Friday executes at Monday's opening price.
    def features(history, sessions, symbol, rules):
        assert all(row["as_of_date"] <= days[1] for row in history)
        return [
            {
                "symbol": symbol,
                "signal_date": day,
                "close": 100,
                "adx14": 30,
                "adv30": 200_000_000,
                "initial_stop_anchor": 90,
                "filtered": index == 0,
                "exit_signal": index == 1,
            }
            for index, day in enumerate(days[:2])
        ]

    monkeypatch.setattr(replay, "feature_series", features)
    result = replay.simulate(
        {"share": ("TEST", rows)},
        days,
        policy=replay.Policy(initial_capital=10_000),
        start_date=days[0],
        end_date=days[1],
        membership_by_day=membership,
    )
    assert [fill["date"] for fill in result["fills"]] == [days[1], days[2]]
    assert [point["date"] for point in result["equity_curve"]] == days[:2]
    assert result["performance"]["final_equity"] == pytest.approx(9997.5)
    assert result["performance"]["open_positions"] == 1
    assert result["holdings_after_exit_session"] == {}


def test_missing_target_open_is_reported_without_using_a_later_price(monkeypatch):
    replay, days, rows, membership = replay_fixture(monkeypatch)
    rows = [row for row in rows if row["as_of_date"] != days[3]]
    rows.append(
        {
            "as_of_date": "2026-06-10",
            "open": 500,
            "high": 500,
            "low": 500,
            "close": 500,
            "volume": 100,
        }
    )
    days.append("2026-06-10")
    membership[days[-1]] = {"snapshot_id": "after", "symbols": []}
    monkeypatch.setattr(
        replay,
        "feature_series",
        lambda *_: [
            {
                "symbol": "TEST",
                "signal_date": days[0],
                "close": 100,
                "adx14": 30,
                "adv30": 200_000_000,
                "initial_stop_anchor": 90,
                "filtered": True,
                "exit_signal": False,
            }
        ],
    )
    result = replay.simulate(
        {"share": ("TEST", rows)},
        days,
        policy=replay.Policy(initial_capital=10_000),
        start_date=days[0],
        end_date=days[-1],
        membership_by_day=membership,
    )
    assert [fill["side"] for fill in result["fills"]] == ["BUY"]
    assert result["exit_records"][0]["fill_status"] == "MISSING_OPEN"
    assert result["exit_records"][0]["target_execution_session"] == "2026-06-09"


def test_backtest_enters_and_exits_at_following_open_with_cash_and_fees(monkeypatch):
    days = ["2022-01-03", "2022-01-04", "2022-01-05"]
    bars = [
        {
            "as_of_date": days[0],
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 2_000_000,
        },
        {
            "as_of_date": days[1],
            "open": 100,
            "high": 101,
            "low": 94,
            "close": 95,
            "volume": 2_000_000,
        },
        {
            "as_of_date": days[2],
            "open": 90,
            "high": 91,
            "low": 89,
            "close": 90,
            "volume": 2_000_000,
        },
    ]

    def features(_bars, _sessions, _symbol, _rules=None):
        return [
            {
                "symbol": "TEST",
                "signal_date": days[0],
                "close": 100,
                "adx14": 30,
                "adv30": 200_000_000,
                "initial_stop_anchor": 90,
                "filtered": True,
                "exit_signal": False,
            },
            {
                "symbol": "TEST",
                "signal_date": days[1],
                "close": 95,
                "adx14": 30,
                "adv30": 200_000_000,
                "initial_stop_anchor": 90,
                "filtered": False,
                "exit_signal": True,
            },
        ]

    monkeypatch.setattr(positional_trend_backtest, "feature_series", features)
    policy = positional_trend_backtest.Policy(initial_capital=1_000, max_positions=1, max_name_fraction=1)
    result = positional_trend_backtest.simulate(
        {"id": ("TEST", bars)}, days, policy=policy, end_date=days[-1]
    )
    assert [fill["date"] for fill in result["fills"]] == days[1:]
    assert [fill["side"] for fill in result["fills"]] == ["BUY", "SELL"]
    assert result["fills"][0]["shares"] == 1
    assert result["trades"][0]["exit_signal_date"] == days[1]
    assert result["performance"]["final_equity"] == 989.525
    assert result["performance"]["open_positions"] == 0


def test_pyramid_add_sizes_as_independent_order_with_zero_prior_nominal_risk(monkeypatch):
    days = [f"2022-01-0{i}" for i in range(3, 8)]
    prices = [
        (100, 101, 99, 100),
        (100, 121, 99, 120),
        (122, 126, 120, 125),
        (125, 126, 89, 90),
        (85, 90, 84, 85),
    ]
    bars = [
        {"as_of_date": day, "open": o, "high": h, "low": l, "close": c, "volume": 2_000_000}
        for day, (o, h, l, c) in zip(days, prices)
    ]

    def features(_bars, _sessions, _symbol, _rules=None):
        return [
            {
                "symbol": "TEST",
                "signal_date": days[0],
                "close": 100,
                "adx14": 30,
                "adv30": 200_000_000,
                "initial_stop_anchor": 90,
                "filtered": True,
                "exit_signal": False,
            },
            {
                "symbol": "TEST",
                "signal_date": days[1],
                "close": 120,
                "adx14": 20,
                "adv30": 200_000_000,
                "initial_stop_anchor": 110,
                "filtered": True,
                "exit_signal": False,
            },
            {
                "symbol": "TEST",
                "signal_date": days[2],
                "close": 125,
                "adx14": 45,
                "adv30": 200_000_000,
                "initial_stop_anchor": 115,
                "filtered": True,
                "exit_signal": False,
            },
            {
                "symbol": "TEST",
                "signal_date": days[3],
                "close": 90,
                "adx14": 15,
                "adv30": 200_000_000,
                "initial_stop_anchor": 100,
                "filtered": False,
                "exit_signal": True,
            },
        ]

    monkeypatch.setattr(positional_trend_backtest, "feature_series", features)
    base = positional_trend_backtest.Policy(initial_capital=100_000, max_positions=1)
    on = positional_trend_backtest.simulate(
        {"id": ("TEST", bars)},
        days,
        policy=positional_trend_backtest.Policy(
            initial_capital=100_000, max_positions=1, enable_pyramiding=True
        ),
        end_date=days[-1],
    )
    off = positional_trend_backtest.simulate({"id": ("TEST", bars)}, days, policy=base, end_date=days[-1])
    assert [fill["side"] for fill in on["fills"]] == ["BUY", "PYRAMID_ADD", "SELL"]
    assert on["fills"][1]["date"] == days[2]
    assert on["fills"][1]["shares"] == 83
    assert on["trades"][0]["pyramid_adds"] == 1
    assert on["trades"][0]["shares"] == 183
    assert on["fills"][1]["shares"] * (122 - 110) <= on["fills"][1]["equity_at_open"] * 0.01
    assert on["fills"][1]["order_fraction_of_equity"] <= 0.10
    assert on["fills"][1]["name_fraction_after"] > 0.10
    assert on["execution_skips"]["pyramid_prior_risk_not_zero"] == 1
    assert [fill["side"] for fill in off["fills"]] == ["BUY", "SELL"]


def test_new_candidate_and_pyramid_add_share_adx_ranking(monkeypatch):
    days = ["2022-01-03", "2022-01-04", "2022-01-05"]

    def bars(prices):
        return [
            {
                "as_of_date": day,
                "open": price,
                "high": price + 2,
                "low": price - 2,
                "close": price,
                "volume": 2_000_000,
            }
            for day, price in zip(days, prices)
        ]

    def features(_bars, _sessions, symbol, _rules=None):
        if symbol == "A":
            return [
                {
                    "symbol": "A",
                    "signal_date": days[0],
                    "close": 100,
                    "adx14": 30,
                    "adv30": 200_000_000,
                    "initial_stop_anchor": 90,
                    "filtered": True,
                    "exit_signal": False,
                },
                {
                    "symbol": "A",
                    "signal_date": days[1],
                    "close": 120,
                    "adx14": 35,
                    "adv30": 200_000_000,
                    "initial_stop_anchor": 110,
                    "filtered": True,
                    "exit_signal": False,
                },
            ]
        return [
            {
                "symbol": "B",
                "signal_date": days[1],
                "close": 100,
                "adx14": 40,
                "adv30": 200_000_000,
                "initial_stop_anchor": 90,
                "filtered": True,
                "exit_signal": False,
            }
        ]

    monkeypatch.setattr(positional_trend_backtest, "feature_series", features)
    result = positional_trend_backtest.simulate(
        {"a": ("A", bars([100, 100, 122])), "b": ("B", bars([100, 100, 100]))},
        days,
        policy=positional_trend_backtest.Policy(
            initial_capital=100_000, max_positions=2, enable_pyramiding=True
        ),
        end_date=days[-1],
    )
    assert [(fill["date"], fill["symbol"], fill["side"]) for fill in result["fills"]] == [
        (days[1], "A", "BUY"),
        (days[2], "B", "BUY"),
        (days[2], "A", "PYRAMID_ADD"),
    ]


@pytest.mark.parametrize(
    "opening,expected_buy", [(103, True), (103.01, False), (90, False), (89, False)]
)
def test_gap_and_stop_boundary_use_following_open(monkeypatch, opening, expected_buy):
    days = ["2022-01-03", "2022-01-04"]
    bars = [
        {
            "as_of_date": day,
            "open": price,
            "high": max(price, 100) + 1,
            "low": min(price, 100) - 1,
            "close": 100,
            "volume": 2_000_000,
        }
        for day, price in zip(days, [100, opening])
    ]
    signal = {
        "symbol": "A",
        "signal_date": days[0],
        "close": 100,
        "adx14": 30,
        "adv30": 200_000_000,
        "initial_stop_anchor": 90,
        "filtered": True,
        "exit_signal": False,
    }
    monkeypatch.setattr(replay, "feature_series", lambda *args: [signal])
    result = replay.simulate(
        {"a": ("A", bars)}, days, policy=replay.Policy(), start_date=days[0], end_date=days[-1]
    )
    assert bool(result["fills"]) is expected_buy
    if expected_buy:
        assert result["fills"][0]["date"] == days[1]
        assert result["fills"][0]["price"] == opening


def test_exit_precedes_ranked_entries_and_ranking_has_three_ties(monkeypatch):
    days = ["2022-01-03", "2022-01-04", "2022-01-05"]
    symbols = ("HELD", "C", "B", "A", "D")
    base = {
        "close": 100,
        "adx14": 30,
        "adv30": 200_000_000,
        "initial_stop_anchor": 90,
        "filtered": True,
        "exit_signal": False,
    }
    signals = {
        "HELD": [
            {**base, "symbol": "HELD", "signal_date": days[0]},
            {
                **base,
                "symbol": "HELD",
                "signal_date": days[1],
                "filtered": False,
                "exit_signal": True,
            },
        ]
    }
    for symbol in symbols[1:]:
        signals[symbol] = [{**base, "symbol": symbol, "signal_date": days[1]}]
    signals["B"][0]["adv30"] *= 2
    signals["D"][0]["adx14"] += 1
    bars = [
        {"as_of_date": day, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 2_000_000}
        for day in days
    ]
    monkeypatch.setattr(
        replay, "feature_series", lambda history, sessions, symbol, rules: signals[symbol]
    )
    result = replay.simulate(
        {symbol: (symbol, bars) for symbol in symbols},
        days,
        policy=replay.Policy(max_positions=4),
        start_date=days[0],
        end_date=days[-1],
    )
    last = [fill for fill in result["fills"] if fill["date"] == days[-1]]
    assert [(fill["side"], fill["symbol"]) for fill in last] == [
        ("SELL", "HELD"),
        ("BUY", "D"),
        ("BUY", "B"),
        ("BUY", "A"),
        ("BUY", "C"),
    ]
