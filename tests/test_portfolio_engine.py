from datetime import date
from decimal import Decimal

import pytest

from src.backtesting import BacktestStep, run
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.portfolio_engine import (
    Candidate,
    DecisionType,
    ExecutionAssumptions,
    Holding,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
    evaluate,
)


def test_gap_stop_sells_at_open_and_frees_cash_before_buying():
    state = PortfolioState(
        Money("0"),
        (Holding("OLD", Quantity(10), Money("100"), Money("90"), Decimal(80)),),
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
        [Candidate("NEW", Decimal(90))],
        bars,
    )

    assert decisions[0].type == DecisionType.HARD_STOP_GAP_OPEN
    assert decisions[0].execution_price == Money("85")
    assert all(decision.type != DecisionType.BUY for decision in decisions)
    assert not next_state.holdings
    assert next_state.cash == Money("850")

    next_day = MarketBar(
        "NEW", date(2026, 1, 5), Decimal(50), Decimal(55), Decimal(49), Decimal(54)
    )
    next_decisions, next_day_state = evaluate(
        next_state,
        PortfolioPolicy(1, Decimal(40), Decimal(1)),
        [Candidate("NEW", Decimal(90))],
        {"NEW": next_day},
    )
    assert next_decisions[0].type == DecisionType.BUY
    assert next_day_state.holdings[0].instrument_id == "NEW"


def test_intraday_stop_fills_at_stop_price():
    state = PortfolioState(
        Money("0"), (Holding("ABC", Quantity(1), Money("100"), Money("90"), Decimal(80)),)
    )
    bar = MarketBar("ABC", date(2026, 1, 2), Decimal(100), Decimal(102), Decimal(89), Decimal(95))

    decisions, _ = evaluate(state, PortfolioPolicy(1, Decimal(40)), [], {"ABC": bar})

    assert decisions[0].type == DecisionType.HARD_STOP_INTRADAY
    assert decisions[0].execution_price == Money("90")


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
        Candidate("NEW", Decimal(70)),
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
        [Candidate("NEW", Decimal(90))],
        {"NEW": bar},
    )
    assert decisions[0].type == DecisionType.BUY
    assert decisions[0].units.units == 5


def test_candidate_size_multiplier_scales_entry_allocation():
    bar = MarketBar("NEW", date(2026, 1, 2), Decimal(10), Decimal(11), Decimal(9), Decimal(10))
    decisions, _ = evaluate(
        PortfolioState(Money(1000)),
        PortfolioPolicy(1, Decimal(40), Decimal("0.5")),
        [Candidate("NEW", Decimal(90), Decimal("0.5"))],
        {"NEW": bar},
    )
    assert decisions[0].units.units == 25


def test_swap_cost_basis_points_raise_required_score_advantage():
    state = PortfolioState(Money(1000), (Holding("OLD", Quantity(2), Money(100), Money(80), Decimal(50)),))
    bars = {
        "OLD": MarketBar("OLD", date(2026, 1, 2), Decimal(100), Decimal(101), Decimal(99), Decimal(100)),
        "NEW": MarketBar("NEW", date(2026, 1, 2), Decimal(100), Decimal(101), Decimal(99), Decimal(100)),
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
        "OLD": MarketBar("OLD", date(2026, 6, 1), Decimal(100), Decimal(101), Decimal(99), Decimal(100)),
        "NEW": MarketBar("NEW", date(2026, 6, 1), Decimal(100), Decimal(101), Decimal(99), Decimal(100)),
    }
    decisions, _ = evaluate(
        state,
        PortfolioPolicy(1, Decimal(40), Decimal(1), Decimal(0), Decimal(0), ltcg_hold_days=365),
        [Candidate("NEW", Decimal(90))],
        bars,
    )
    assert all(decision.type != DecisionType.SWAP_SELL for decision in decisions)


def test_tax_cost_is_applied_only_to_sell_execution():
    state = PortfolioState(Money(0), (Holding("ABC", Quantity(1), Money(100), Money(90), Decimal(0)),))
    bar = MarketBar("ABC", date(2026, 1, 2), Decimal(100), Decimal(101), Decimal(89), Decimal(95))
    decisions, _ = evaluate(state, PortfolioPolicy(1, Decimal(40)), [], {"ABC": bar}, ExecutionAssumptions(tax_bps=Decimal(100)))
    assert decisions[0].fee == Money("0.9")


def test_rebalance_frequency_is_validated_and_preserved_in_policy():
    assert PortfolioPolicy(1, Decimal(40), rebalance_frequency="BIWEEKLY").rebalance_frequency == "BIWEEKLY"
    with pytest.raises(DomainValidationError):
        PortfolioPolicy(1, Decimal(40), rebalance_frequency="WEEKLY")


def test_risk_off_regime_suppresses_entries_but_not_later_risk_on_entry():
    bars = {
        "NEW": MarketBar("NEW", date(2026, 1, 2), Decimal(10), Decimal(11), Decimal(9), Decimal(10))
    }
    steps = (
        BacktestStep(date(2026, 1, 2), (Candidate("NEW", Decimal(90)),), bars, "RISK_OFF"),
        BacktestStep(date(2026, 1, 3), (Candidate("NEW", Decimal(90)),), {"NEW": MarketBar("NEW", date(2026, 1, 3), Decimal(10), Decimal(11), Decimal(9), Decimal(10))}, "RISK_ON"),
    )
    result = run(PortfolioState(Money(100)), PortfolioPolicy(1, Decimal(40)), steps)
    assert len(result.fills) == 1
    assert result.fills[0].as_of_date == date(2026, 1, 3)
