from datetime import date
from decimal import Decimal

from src.platform_kernel import Money, Quantity
from src.portfolio_engine import Candidate, DecisionType, Holding, MarketBar, PortfolioPolicy, PortfolioState, evaluate


def test_gap_stop_sells_at_open_and_frees_cash_before_buying():
    state = PortfolioState(
        Money("100"),
        (Holding("OLD", Quantity(10), Money("100"), Money("90"), Decimal("80")),),
    )
    bars = {
        "OLD": MarketBar("OLD", date(2026, 1, 2), Decimal("85"), Decimal("86"), Decimal("80"), Decimal("82")),
        "NEW": MarketBar("NEW", date(2026, 1, 2), Decimal("50"), Decimal("55"), Decimal("49"), Decimal("54")),
    }

    decisions, next_state = evaluate(state, PortfolioPolicy(1, Decimal("40"), Decimal("1")), [Candidate("NEW", Decimal("90"))], bars)

    assert decisions[0].type == DecisionType.HARD_STOP_GAP_OPEN
    assert decisions[0].execution_price == Money("85")
    assert decisions[1].type == DecisionType.BUY
    assert next_state.holdings[0].instrument_id == "NEW"


def test_intraday_stop_fills_at_stop_price():
    state = PortfolioState(Money("0"), (Holding("ABC", Quantity(1), Money("100"), Money("90"), Decimal("80")),))
    bar = MarketBar("ABC", date(2026, 1, 2), Decimal("100"), Decimal("102"), Decimal("89"), Decimal("95"))

    decisions, _ = evaluate(state, PortfolioPolicy(1, Decimal("40")), [], {"ABC": bar})

    assert decisions[0].type == DecisionType.HARD_STOP_INTRADAY
    assert decisions[0].execution_price == Money("90")


def test_engine_pyramids_winner_then_defers_swap_reinvestment_to_next_bar():
    state = PortfolioState(
        Money("1000"),
        (
            Holding("WIN", Quantity(2), Money("100"), Money("110"), Decimal("80")),
            Holding("WEAK", Quantity(2), Money("100"), Money("80"), Decimal("50")),
        ),
    )
    bars = {
        "WIN": MarketBar("WIN", date(2026, 1, 2), Decimal("120"), Decimal("125"), Decimal("119"), Decimal("121")),
        "WEAK": MarketBar("WEAK", date(2026, 1, 2), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100")),
        "NEW": MarketBar("NEW", date(2026, 1, 2), Decimal("100"), Decimal("102"), Decimal("99"), Decimal("101")),
    }
    candidates = [Candidate("WIN", Decimal("90")), Candidate("WEAK", Decimal("50")), Candidate("NEW", Decimal("70"))]

    decisions, next_state = evaluate(state, PortfolioPolicy(2, Decimal("40"), Decimal("0.25"), Decimal("0.25"), Decimal("1")), candidates, bars)

    assert decisions[0].type == DecisionType.PYRAMID_ADD
    assert any(item.type == DecisionType.SWAP_SELL for item in decisions)
    assert {holding.instrument_id for holding in next_state.holdings} == {"WIN"}
