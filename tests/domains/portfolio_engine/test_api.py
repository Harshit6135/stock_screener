from datetime import date
from decimal import Decimal
from decimal import Decimal as D

import pytest

from src.domains.portfolio_engine import (
    Candidate,
    DecisionType,
    ExecutionAssumptions,
    Holding,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
    evaluate,
)
from src.platform_kernel import DomainValidationError, Money, Quantity


def bar(symbol="A", opening=100, low=99, close=100):
    return MarketBar(
        symbol, date(2026, 7, 6), D(opening), D(max(opening, close) + 1), D(low), D(close)
    )


def state(stop=95, cash=0):
    return PortfolioState(
        Money(cash), (Holding("A", Quantity(10), Money(100), Money(stop), D(80)),)
    )


def test_weekly_close_stop_sells_even_when_monday_recovers():
    decisions, _ = evaluate(
        state(),
        PortfolioPolicy(1, D(40)),
        [Candidate("A", D(80), atr=D(2), signal_close=D(94))],
        {"A": bar(opening=102, low=101, close=103)},
    )
    assert [d.type for d in decisions] == [DecisionType.STOP_LOSS]
    assert decisions[0].execution_price == Money(102)


def test_latest_friday_atr_stop_never_moves_down():
    _, result = evaluate(
        state(stop=90),
        PortfolioPolicy(1, D(40)),
        [Candidate("A", D(80), atr=D(2), signal_close=D(100))],
        {"A": bar()},
    )
    assert result.holdings[0].current_stop == Money(96)
    _, result = evaluate(
        result,
        PortfolioPolicy(1, D(40)),
        [Candidate("A", D(80), atr=D(5), signal_close=D(100))],
        {"A": bar()},
    )
    assert result.holdings[0].current_stop == Money(96)


def test_midweek_normal_stop_breach_does_not_exit_or_trail():
    decisions, result = evaluate(
        state(),
        PortfolioPolicy(1, D(40), check_daily_sl=False),
        [],
        {"A": bar(opening=94, low=93, close=94)},
        is_rebalance_day=False,
    )
    assert [d.type for d in decisions] == [DecisionType.NO_ACTION]
    assert result.holdings[0].current_stop == Money(95)


def test_hard_stop_daily_even_with_legacy_daily_flag_off():
    for opening, low, expected in [(94, 92, "92.15"), (90, 89, "90")]:
        decisions, result = evaluate(
            state(),
            PortfolioPolicy(1, D(40), check_daily_sl=False),
            [],
            {"A": bar(opening=opening, low=low, close=opening)},
            is_rebalance_day=False,
        )
        assert [d.type for d in decisions] == [DecisionType.HARD_STOP]
        assert decisions[0].execution_price == Money(expected)
        assert not result.holdings


def test_intraday_exit_cannot_create_opening_vacancy_or_rebuy():
    decisions, result = evaluate(
        state(cash=1000),
        PortfolioPolicy(1, D(40), max_position_fraction=D(1)),
        [Candidate("A", D(80), atr=D(3), signal_close=D(100)), Candidate("B", D(81), atr=D(3))],
        {"A": bar(low=90), "B": bar("B")},
    )
    assert [d.type for d in decisions] == [DecisionType.HARD_STOP]
    assert not result.holdings


def test_entry_stop_uses_atr_and_missing_atr_does_not_buy():
    policy = PortfolioPolicy(1, D(40), max_position_fraction=D(1))
    _, result = evaluate(
        PortfolioState(Money(1000)), policy, [Candidate("A", D(80), atr=D(3))], {"A": bar()}
    )
    assert result.holdings[0].current_stop == Money(94)
    decisions, _ = evaluate(
        PortfolioState(Money(1000)), policy, [Candidate("A", D(80))], {"A": bar()}
    )
    assert decisions[0].type == DecisionType.NO_ACTION


def test_gap_stop_sells_at_open_and_frees_cash_before_buying():
    state = PortfolioState(
        Money("0"), (Holding("OLD", Quantity(10), Money("100"), Money("90"), Decimal(80)),)
    )
    bars = {
        "OLD": MarketBar(
            "OLD", date(2026, 1, 2), Decimal(85), Decimal(86), Decimal(80), Decimal(82)
        ),
        "NEW": MarketBar(
            "NEW", date(2026, 1, 2), Decimal(50), Decimal(55), Decimal(49), Decimal(54)
        ),
    }
    decisions, next_state = evaluate(
        state,
        PortfolioPolicy(1, Decimal(40), Decimal(1)),
        [Candidate("NEW", Decimal(90), atr=Decimal(2))],
        bars,
    )
    assert decisions[0].type == DecisionType.HARD_STOP
    assert decisions[0].execution_price == Money("85")
    buy_decisions = [d for d in decisions if d.type == DecisionType.BUY]
    assert len(buy_decisions) == 1
    assert buy_decisions[0].instrument_id == "NEW"
    assert next_state.holdings[0].instrument_id == "NEW"


def test_intraday_stop_fills_at_stop_price():
    state = PortfolioState(
        Money("0"), (Holding("ABC", Quantity(1), Money("100"), Money("90"), Decimal(80)),)
    )
    bar = MarketBar("ABC", date(2026, 1, 2), Decimal(100), Decimal(102), Decimal(87), Decimal(95))
    decisions, _ = evaluate(
        state, PortfolioPolicy(1, Decimal(40)), [], {"ABC": bar}, is_rebalance_day=False
    )
    assert decisions[0].type == DecisionType.HARD_STOP
    assert decisions[0].execution_price == Money("87.3")


def test_engine_pyramids_winner_then_executes_prior_close_swap_at_open():
    state = PortfolioState(
        Money("1000"),
        (
            Holding("WIN", Quantity(2), Money("100"), Money("110"), Decimal(80)),
            Holding("WEAK", Quantity(2), Money("100"), Money("80"), Decimal(50)),
        ),
    )
    bars = {
        "WIN": MarketBar(
            "WIN", date(2026, 1, 2), Decimal(120), Decimal(125), Decimal(119), Decimal(121)
        ),
        "WEAK": MarketBar(
            "WEAK", date(2026, 1, 2), Decimal(100), Decimal(101), Decimal(99), Decimal(100)
        ),
        "NEW": MarketBar(
            "NEW", date(2026, 1, 2), Decimal(100), Decimal(102), Decimal(99), Decimal(101)
        ),
    }
    candidates = [
        Candidate("WIN", Decimal(90)),
        Candidate("WEAK", Decimal(50)),
        Candidate("NEW", Decimal(70), atr=Decimal(2)),
    ]
    decisions, next_state = evaluate(
        state,
        PortfolioPolicy(2, Decimal(40), Decimal("0.25"), Decimal("0.25"), Decimal(1)),
        candidates,
        bars,
    )
    assert decisions[0].type == DecisionType.PYRAMID_ADD
    assert any(item.type == DecisionType.SWAP_SELL for item in decisions)
    assert {holding.instrument_id for holding in next_state.holdings} == {"WIN", "NEW"}


def test_market_impact_limit_caps_entry_to_bar_volume():
    bar = MarketBar("NEW", date(2026, 1, 2), Decimal(10), Decimal(11), Decimal(9), Decimal(10), 10)
    decisions, _ = evaluate(
        PortfolioState(Money(1000)),
        PortfolioPolicy(1, Decimal(40), Decimal(1), max_volume_participation=Decimal("0.5")),
        [Candidate("NEW", Decimal(90), atr=Decimal(2))],
        {"NEW": bar},
    )
    assert decisions[0].type == DecisionType.BUY
    assert decisions[0].units.units == 5


def test_candidate_size_multiplier_scales_entry_allocation():
    bar = MarketBar("NEW", date(2026, 1, 2), Decimal(10), Decimal(11), Decimal(9), Decimal(10))
    decisions, _ = evaluate(
        PortfolioState(Money(1000)),
        PortfolioPolicy(1, Decimal(40), Decimal("0.5")),
        [Candidate("NEW", Decimal(90), Decimal("0.5"), atr=Decimal(2))],
        {"NEW": bar},
    )
    assert decisions[0].units.units == 25


def test_swap_cost_basis_points_raise_required_score_advantage():
    state = PortfolioState(
        Money(1000), (Holding("OLD", Quantity(2), Money(100), Money(80), Decimal(50)),)
    )
    bars = {
        "OLD": MarketBar(
            "OLD", date(2026, 1, 2), Decimal(100), Decimal(101), Decimal(99), Decimal(100)
        ),
        "NEW": MarketBar(
            "NEW", date(2026, 1, 2), Decimal(100), Decimal(101), Decimal(99), Decimal(100)
        ),
    }
    decisions, _ = evaluate(
        state,
        PortfolioPolicy(1, Decimal(40), Decimal(1), Decimal("0.25"), swap_cost_bps=2000),
        [Candidate("NEW", Decimal(70))],
        bars,
    )
    assert all(decision.type != DecisionType.SWAP_SELL for decision in decisions)


def test_ltcg_hold_policy_prevents_short_term_swap():
    state = PortfolioState(
        Money(1000),
        (Holding("OLD", Quantity(2), Money(100), Money(80), Decimal(50), date(2026, 1, 1)),),
    )
    bars = {
        "OLD": MarketBar(
            "OLD", date(2026, 6, 1), Decimal(100), Decimal(101), Decimal(99), Decimal(100)
        ),
        "NEW": MarketBar(
            "NEW", date(2026, 6, 1), Decimal(100), Decimal(101), Decimal(99), Decimal(100)
        ),
    }
    decisions, _ = evaluate(
        state,
        PortfolioPolicy(1, Decimal(40), Decimal(1), Decimal(0), Decimal(0), ltcg_hold_days=365),
        [Candidate("NEW", Decimal(90))],
        bars,
    )
    assert all(decision.type != DecisionType.SWAP_SELL for decision in decisions)


def test_tax_cost_is_applied_only_to_sell_execution():
    state = PortfolioState(
        Money(0), (Holding("ABC", Quantity(1), Money(100), Money(90), Decimal(0)),)
    )
    bar = MarketBar("ABC", date(2026, 1, 2), Decimal(100), Decimal(101), Decimal(89), Decimal(95))
    decisions, _ = evaluate(
        state,
        PortfolioPolicy(1, Decimal(40)),
        [],
        {"ABC": bar},
        ExecutionAssumptions(tax_bps=Decimal(100)),
    )
    assert decisions[0].fee == Money("1")


def test_rebalance_frequency_is_validated_and_preserved_in_policy():
    assert (
        PortfolioPolicy(1, Decimal(40), rebalance_frequency="BIWEEKLY").rebalance_frequency
        == "BIWEEKLY"
    )
    assert (
        PortfolioPolicy(1, Decimal(40), rebalance_frequency="WEEKLY").rebalance_frequency
        == "WEEKLY"
    )
    with pytest.raises(DomainValidationError):
        PortfolioPolicy(1, Decimal(40), rebalance_frequency="YEARLY")


def test_swap_proceeds_fund_replacement_without_losing_equity():
    state = PortfolioState(
        Money(0), (Holding("OLD", Quantity(10), Money(100), Money(80), Decimal(50)),)
    )
    bars = {
        "OLD": MarketBar(
            "OLD", date(2026, 1, 5), Decimal(100), Decimal(101), Decimal(99), Decimal(100)
        ),
        "NEW": MarketBar(
            "NEW", date(2026, 1, 5), Decimal(50), Decimal(51), Decimal(49), Decimal(50)
        ),
    }
    decisions, next_state = evaluate(
        state,
        PortfolioPolicy(1, Decimal(40), Decimal(1), Decimal("0.25")),
        (Candidate("OLD", Decimal(50)), Candidate("NEW", Decimal(90), atr=Decimal(2))),
        bars,
    )
    assert [decision.type for decision in decisions] == [DecisionType.SWAP_SELL, DecisionType.BUY]
    assert next_state.cash == Money(0)
    assert [(holding.instrument_id, holding.units.units) for holding in next_state.holdings] == [
        ("NEW", 20)
    ]


def test_vacancy_buy_sizes_from_total_equity_and_is_capped_by_cash():
    state = PortfolioState(
        Money(5000), (Holding("OLD", Quantity(50), Money(100), Money(80), Decimal(80)),)
    )
    bars = {
        "OLD": MarketBar(
            "OLD", date(2026, 1, 5), Decimal(100), Decimal(101), Decimal(99), Decimal(100)
        ),
        "NEW": MarketBar(
            "NEW", date(2026, 1, 5), Decimal(10), Decimal(11), Decimal(9), Decimal(10)
        ),
    }
    decisions, next_state = evaluate(
        state,
        PortfolioPolicy(2, Decimal(40), Decimal("0.5")),
        (Candidate("OLD", Decimal(80)), Candidate("NEW", Decimal(90), atr=Decimal(2))),
        bars,
    )
    buy = next(decision for decision in decisions if decision.type == DecisionType.BUY)
    assert buy.units == Quantity(500)
    assert next_state.cash == Money(0)


def test_prior_close_score_exit_executes_at_next_open_not_current_close():
    state = PortfolioState(
        Money(0),
        (Holding("OLD", Quantity(1), Money(100), Money(50), Decimal(0)),),
    )
    bars = {
        "OLD": MarketBar("OLD", date(2026, 1, 2), 90, 120, 80, 110),
        "NEW": MarketBar("NEW", date(2026, 1, 2), 100, 110, 90, 105),
    }

    decisions, state = evaluate(state, PortfolioPolicy(1, 1, 1), (Candidate("NEW", 100),), bars)

    assert decisions[0].execution_price == Money(90)
    assert all(decision.execution_price != Money(110) for decision in decisions)
    assert state.cash == Money(90)


def test_exit_proceeds_can_finance_same_date_open_buy():
    state = PortfolioState(
        Money(20),
        (Holding("OLD", Quantity(1), Money(100), Money(50), Decimal(0)),),
    )
    bars = {
        "OLD": MarketBar("OLD", date(2026, 1, 2), 90, 120, 80, 110),
        "NEW": MarketBar("NEW", date(2026, 1, 2), 100, 110, 90, 105),
    }

    decisions, next_state = evaluate(
        state, PortfolioPolicy(1, 1, 1), (Candidate("NEW", 100, atr=Decimal(10)),), bars
    )

    # Bug-fix 3: released cash is now available for same-day buys.
    types = [decision.type for decision in decisions]
    assert DecisionType.UNIVERSE_EXIT in types
    assert DecisionType.BUY in types
    assert next_state.holdings[0].instrument_id == "NEW"


def test_portfolio_policy_backtest_options():
    # Verify check_daily_sl and mid_week_buy and WEEKLY rebalance frequency
    policy = PortfolioPolicy(
        max_positions=10,
        exit_score=Decimal(40),
        rebalance_frequency="BIWEEKLY",
        check_daily_sl=False,
        mid_week_buy=False,
        pyramid_fraction=Decimal("0.5"),
    )
    assert policy.rebalance_frequency == "BIWEEKLY"
    assert policy.check_daily_sl is False
    assert policy.mid_week_buy is False
    assert policy.pyramid_fraction == Decimal("0.5")

    # In evaluate:
    # When is_rebalance_day is False and mid_week_buy is False, candidates should not be bought
    state = PortfolioState(Money(Decimal(100000)))
    bar = MarketBar(
        "INFY", date(2026, 9, 8), Decimal(100), Decimal(105), Decimal(95), Decimal(102), 1000
    )
    candidate = Candidate("INFY", Decimal(80), atr=Decimal(5))

    decisions, next_state = evaluate(
        state,
        policy,
        [candidate],
        {"INFY": bar},
        is_rebalance_day=False,
    )
    assert len(next_state.holdings) == 0
    assert decisions[0].type.value == "NO_ACTION"

    # On rebalance day, candidate IS bought
    decisions, next_state = evaluate(
        state,
        policy,
        [candidate],
        {"INFY": bar},
        is_rebalance_day=True,
    )
    assert len(decisions) == 1
    assert decisions[0].type.value == "BUY"
