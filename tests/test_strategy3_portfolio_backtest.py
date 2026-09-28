import pytest

# Historical Strategy 3 coverage is retained for the retirement audit only.
pytestmark = pytest.mark.skip(reason="Strategy 3 is retired; Task 4.3 remains incomplete until runtime source is removed")

from tools import strategy3_portfolio_backtest
from tools.strategy3_portfolio_backtest import Policy, simulate


def _bars(days, prices):
    return [{"as_of_date": day, "open": price, "high": price + 2,
             "low": price - 2, "close": price, "volume": 1_000_000}
            for day, price in zip(days, prices)]


def test_next_open_entry_and_second_session_horizon_close():
    days = ["2022-01-03", "2022-01-04", "2022-01-05"]
    signal = {"symbol": "A", "residual_rank": 1, "close": 100,
              "lower_bb20_2": 90, "adv30_value": 200_000_000}
    result = simulate({"a": ("A", _bars(days, [100, 100, 110]))}, days,
                      {days[0]: [signal]}, policy=Policy(initial_capital=100_000,
                                                         holding_sessions=2),
                      start=days[0], end=days[-1])
    assert [(f["date"], f["side"]) for f in result["fills"]] == [
        (days[1], "BUY"), (days[2], "SELL")]
    assert result["fills"][0]["shares"] == 100
    assert result["trades"][0]["exit_reason"] == "horizon_close"
    assert result["performance"]["final_equity"] == 100_947.5


def test_fixed_stop_can_sell_on_entry_day():
    days = ["2022-01-03", "2022-01-04"]
    bars = _bars(days, [100, 100])
    bars[1]["low"] = 89
    signal = {"symbol": "A", "residual_rank": 1, "close": 100,
              "lower_bb20_2": 90, "adv30_value": 200_000_000}
    result = simulate({"a": ("A", bars)}, days, {days[0]: [signal]},
                      policy=Policy(initial_capital=100_000),
                      start=days[0], end=days[-1])
    assert result["trades"][0]["exit_reason"] == "intraday_stop"
    assert result["trades"][0]["exit_price"] == 90
    assert result["performance"]["final_equity"] == 98_952.5


def test_signal_builder_uses_v4_rank_and_filters(monkeypatch):
    day = "2022-01-03"
    feature = {"residual_score": 4.0, "relative_volume_50": 2.0,
               "bbw_prior_percentile_126": .10, "adv30_value": 200_000_000,
               "prior20_volume": 100, "prior252_volume": 200,
               "lower_bb20_2": 90, "cross_ok": True, "close": 100}
    monkeypatch.setattr(strategy3_portfolio_backtest, "early_momentum_feature_series",
                        lambda _bars, _benchmark: {day: feature})
    signals = strategy3_portfolio_backtest.build_signals(
        {"a": ("A", [{"as_of_date": day}])}, [{"as_of_date": day}], day, day)
    assert [item["symbol"] for item in signals[day]] == ["A"]
    assert signals[day][0]["residual_rank"] == 1
