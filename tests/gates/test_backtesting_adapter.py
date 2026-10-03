from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.domains.backtesting import FillModelRevision
from src.domains.portfolio_engine import (
    Candidate,
    ExecutionAssumptions,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
    evaluate,
)
from src.gates.backtesting_adapter import BacktestPortfolioEngineAdapter
from src.platform_kernel import Money


def test_adapter_translates_backtest_costs_to_portfolio_contract():
    adapter = BacktestPortfolioEngineAdapter()
    fill_model = FillModelRevision(
        uuid4(), "1.0.0", slippage_bps=Decimal(25), fee_bps=Decimal(10), tax_bps=Decimal(5)
    )

    assert adapter.execution_assumptions(fill_model) == ExecutionAssumptions(25, 10, 5)


def test_adapter_delegates_portfolio_decisions():
    adapter = BacktestPortfolioEngineAdapter()
    state = PortfolioState(Money(1000))
    policy = PortfolioPolicy(1, Decimal(40))
    candidates = (Candidate("ABC", Decimal(90), atr=Decimal(5)),)
    bars = {"ABC": MarketBar("ABC", date(2026, 1, 2), 100, 110, 99, 105)}
    assumptions = ExecutionAssumptions(10, 5, 2)
    inputs = {
        "is_rebalance_day": True,
        "score_candidates": candidates,
        "forced_universe_exits": frozenset(),
    }

    actual = adapter.evaluate(state, policy, candidates, bars, assumptions, **inputs)
    expected = evaluate(state, policy, candidates, bars, assumptions, **inputs)

    assert actual == expected
