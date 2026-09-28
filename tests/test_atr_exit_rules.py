from datetime import date
from decimal import Decimal as D

from src.platform_kernel import Money, Quantity
from src.portfolio_engine import (
    Candidate,
    DecisionType,
    Holding,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
    evaluate,
)


def bar(symbol="A", opening=100, low=99, close=100):
    return MarketBar(symbol, date(2026, 7, 6), D(opening), D(max(opening, close) + 1), D(low), D(close))


def state(stop=95, cash=0):
    return PortfolioState(Money(cash), (Holding("A", Quantity(10), Money(100), Money(stop), D(80)),))


def test_weekly_close_stop_sells_even_when_monday_recovers():
    decisions, _ = evaluate(state(), PortfolioPolicy(1, D(40)),
        [Candidate("A", D(80), atr=D(2), signal_close=D(94))], {"A": bar(opening=102, low=101, close=103)})
    assert [d.type for d in decisions] == [DecisionType.STOP_LOSS]
    assert decisions[0].execution_price == Money(102)


def test_latest_friday_atr_stop_never_moves_down():
    _, result = evaluate(state(stop=90), PortfolioPolicy(1, D(40)),
        [Candidate("A", D(80), atr=D(2), signal_close=D(100))], {"A": bar()})
    assert result.holdings[0].current_stop == Money(96)
    _, result = evaluate(result, PortfolioPolicy(1, D(40)),
        [Candidate("A", D(80), atr=D(5), signal_close=D(100))], {"A": bar()})
    assert result.holdings[0].current_stop == Money(96)


def test_midweek_normal_stop_breach_does_not_exit_or_trail():
    decisions, result = evaluate(state(), PortfolioPolicy(1, D(40), check_daily_sl=False),
        [], {"A": bar(opening=94, low=93, close=94)}, is_rebalance_day=False)
    assert [d.type for d in decisions] == [DecisionType.NO_ACTION]
    assert result.holdings[0].current_stop == Money(95)


def test_hard_stop_daily_even_with_legacy_daily_flag_off():
    for opening, low, expected in [(94, 92, "92.15"), (90, 89, "90")]:
        decisions, result = evaluate(state(), PortfolioPolicy(1, D(40), check_daily_sl=False),
            [], {"A": bar(opening=opening, low=low, close=opening)}, is_rebalance_day=False)
        assert [d.type for d in decisions] == [DecisionType.HARD_STOP]
        assert decisions[0].execution_price == Money(expected)
        assert not result.holdings


def test_intraday_exit_cannot_create_opening_vacancy_or_rebuy():
    decisions, result = evaluate(state(cash=1000), PortfolioPolicy(1, D(40), max_position_fraction=D(1)),
        [Candidate("A", D(80), atr=D(3), signal_close=D(100)), Candidate("B", D(81), atr=D(3))],
        {"A": bar(low=90), "B": bar("B")})
    assert [d.type for d in decisions] == [DecisionType.HARD_STOP]
    assert not result.holdings


def test_entry_stop_uses_atr_and_missing_atr_does_not_buy():
    policy = PortfolioPolicy(1, D(40), max_position_fraction=D(1))
    _, result = evaluate(PortfolioState(Money(1000)), policy,
                        [Candidate("A", D(80), atr=D(3))], {"A": bar()})
    assert result.holdings[0].current_stop == Money(94)
    decisions, _ = evaluate(PortfolioState(Money(1000)), policy, [Candidate("A", D(80))], {"A": bar()})
    assert decisions[0].type == DecisionType.NO_ACTION
