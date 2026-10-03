from dataclasses import replace
from datetime import date
from decimal import Decimal
from decimal import Decimal as D
from uuid import uuid4

import pytest

from src.domains.backtesting import (
    BacktestExecutionAssumptions,
    BacktestResult,
    BacktestRunManifest,
    BacktestStep,
    FillModelRevision,
)
from src.domains.backtesting import run as _run_backtest
from src.domains.portfolio_engine import (
    Candidate,
    DecisionType,
    ExecutionAssumptions,
    Holding,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
)
from src.domains.portfolio_engine import (
    evaluate as evaluate_portfolio,
)
from src.platform_kernel import DomainValidationError, Money, Quantity


class _PortfolioEnginePort:
    def execution_assumptions(self, fill_model):
        values: BacktestExecutionAssumptions = fill_model.execution_assumptions()
        return ExecutionAssumptions(values.slippage_bps, values.fee_bps, values.tax_bps)

    def evaluate(
        self,
        state,
        policy,
        candidates,
        bars,
        assumptions,
        *,
        is_rebalance_day,
        score_candidates,
        forced_universe_exits,
    ):
        return evaluate_portfolio(
            state,
            policy,
            candidates,
            bars,
            assumptions,
            is_rebalance_day=is_rebalance_day,
            score_candidates=score_candidates,
            forced_universe_exits=forced_universe_exits,
        )


def run(*args, **kwargs):
    return _run_backtest(*args, portfolio_engine=_PortfolioEnginePort(), **kwargs)


def test_in_memory_backtest_uses_pure_engine_and_publishes_no_shared_database():
    bar = MarketBar("ABC", date(2026, 1, 2), Decimal(100), Decimal(110), Decimal(99), Decimal(105))
    result = run(
        PortfolioState(Money("1000")),
        PortfolioPolicy(1, Decimal(40), Decimal(1)),
        (
            BacktestStep(
                date(2026, 1, 2), (Candidate("ABC", Decimal(90), atr=Decimal(5)),), {"ABC": bar}
            ),
        ),
    )
    assert result.final_state.holdings[0].instrument_id == "ABC"
    assert result.equity_curve[0][1] == Decimal(1050)
    assert result.final_prices == {"ABC": Decimal(105)}
    manifest = BacktestRunManifest(
        uuid4(),
        ("market-snapshot",),
        uuid4(),
        uuid4(),
        uuid4(),
        "engine",
        date(2026, 1, 2),
        date(2026, 1, 2),
        {},
        "code",
    )
    payload = replace(result, manifest=manifest).to_payload()
    assert payload["ending_equity"] == Decimal(1050)
    assert payload["open_position_value"] == Decimal(1050)
    assert payload["open_positions"][0]["last_price"] == Decimal(105)
    assert payload["open_positions"][0]["market_value"] == Decimal(1050)


def bar(symbol="A", opening=100, low=99, close=100):
    return MarketBar(
        symbol, date(2026, 7, 6), D(opening), D(max(opening, close) + 1), D(low), D(close)
    )


def state(stop=95, cash=0):
    return PortfolioState(
        Money(cash), (Holding("A", Quantity(10), Money(100), Money(stop), D(80)),)
    )


def test_risk_off_regime_suppresses_entries_but_not_later_risk_on_entry():
    bars = {
        "NEW": MarketBar("NEW", date(2026, 1, 2), Decimal(10), Decimal(11), Decimal(9), Decimal(10))
    }
    steps = (
        BacktestStep(
            date(2026, 1, 2), (Candidate("NEW", Decimal(90), atr=Decimal(2)),), bars, "RISK_OFF"
        ),
        BacktestStep(
            date(2026, 1, 3),
            (Candidate("NEW", Decimal(90), atr=Decimal(2)),),
            {
                "NEW": MarketBar(
                    "NEW", date(2026, 1, 3), Decimal(10), Decimal(11), Decimal(9), Decimal(10)
                )
            },
            "RISK_ON",
        ),
    )
    result = run(PortfolioState(Money(100)), PortfolioPolicy(1, Decimal(40)), steps)
    assert len(result.fills) == 1
    assert result.fills[0].as_of_date == date(2026, 1, 3)


def test_risk_off_rebalance_uses_ranking_score_without_forced_liquidation():
    bar = MarketBar("OLD", date(2026, 1, 5), Decimal(100), Decimal(101), Decimal(99), Decimal(100))
    state = PortfolioState(
        Money(0), (Holding("OLD", Quantity(1), Money(100), Money(90), Decimal(80)),)
    )
    result = run(
        state,
        PortfolioPolicy(1, Decimal(40), rebalance_frequency="WEEKLY"),
        (
            BacktestStep(
                date(2026, 1, 5), (Candidate("OLD", Decimal(80)),), {"OLD": bar}, "RISK_OFF"
            ),
        ),
    )
    assert not result.fills
    assert [holding.instrument_id for holding in result.final_state.holdings] == ["OLD"]


def test_explicit_universe_exit_uses_declared_next_open_and_retains_decision_lineage():
    first = date(2026, 1, 2)
    target = date(2026, 1, 5)
    state = PortfolioState(
        Money("0"), (Holding("OLD", Quantity(2), Money("100"), Money("90"), Decimal(80)),)
    )
    context = {
        "decision_date": first.isoformat(),
        "universe_snapshot_id": "removed-snapshot",
        "price_snapshot_id": "exit-bar",
        "market_revision": "7",
    }
    result = run(
        state,
        PortfolioPolicy(1, Decimal(40)),
        (
            BacktestStep(
                first,
                (Candidate("OLD", Decimal(80)),),
                {"OLD": MarketBar("OLD", first, 100, 101, 99, 100)},
            ),
            BacktestStep(
                target,
                (),
                {"OLD": MarketBar("OLD", target, 110, 111, 109, 110)},
                universe_exits={"OLD": context},
            ),
        ),
    )
    exit_fill = result.fills[-1]
    assert exit_fill.decision_type == DecisionType.UNIVERSE_EXIT
    assert exit_fill.side == "SELL" and exit_fill.price == Decimal(110)
    assert exit_fill.decision_date == first and exit_fill.as_of_date == target
    assert (
        exit_fill.universe_snapshot_id,
        exit_fill.price_snapshot_id,
        exit_fill.market_revision,
    ) == ("removed-snapshot", "exit-bar", "7")
    assert result.equity_curve[0][1] == Decimal(200)
    protective = run(
        state,
        PortfolioPolicy(1, Decimal(40)),
        (
            BacktestStep(
                first,
                (Candidate("OLD", Decimal(80)),),
                {"OLD": MarketBar("OLD", first, 100, 101, 99, 100)},
            ),
            BacktestStep(
                target,
                (),
                {"OLD": MarketBar("OLD", target, 80, 81, 79, 80)},
                universe_exits={"OLD": context},
            ),
        ),
    )
    assert protective.fills[-1].decision_type == DecisionType.HARD_STOP
    assert protective.fills[-1].price == Decimal(80)


def test_post_period_universe_exit_does_not_change_period_valuation():
    first = date(2026, 1, 2)
    target = date(2026, 1, 5)
    state = PortfolioState(
        Money("0"), (Holding("OLD", Quantity(2), Money("100"), Money("90"), Decimal(80)),)
    )
    period = (
        BacktestStep(
            first,
            (Candidate("OLD", Decimal(80)),),
            {"OLD": MarketBar("OLD", first, 100, 101, 99, 100)},
        ),
    )
    settlement = BacktestStep(
        target,
        (),
        {"OLD": MarketBar("OLD", target, 110, 111, 109, 110)},
        universe_exits={
            "OLD": {
                "decision_date": first.isoformat(),
                "universe_snapshot_id": "removed-snapshot",
                "price_snapshot_id": "exit-bar",
                "market_revision": "7",
            }
        },
    )
    result = run(state, PortfolioPolicy(1, Decimal(40)), period, settlement_step=settlement)
    assert len(result.equity_curve) == 1
    assert result.equity_curve[0][1] == Decimal(200)
    assert result.metrics["total_return"] == Decimal(0)
    assert result.trade_counts["sell"] == 0
    assert result.fills[-1].as_of_date == target
    with pytest.raises(DomainValidationError, match="missing declared universe-exit open"):
        run(
            state,
            PortfolioPolicy(1, Decimal(40)),
            period,
            settlement_step=BacktestStep(target, (), {}, universe_exits=settlement.universe_exits),
        )


def test_fill_model_changes_execution_and_metrics():
    run_id = uuid4()
    fill_model = FillModelRevision(uuid4(), "1.0.0", slippage_bps=100, fee_bps=100)
    step = BacktestStep(
        date(2026, 1, 2),
        (Candidate("ABC", 90, atr=Decimal(5)),),
        {"ABC": MarketBar("ABC", date(2026, 1, 2), 100, 110, 99, 105)},
    )
    manifest = BacktestRunManifest(
        run_id,
        ("market-1",),
        uuid4(),
        uuid4(),
        fill_model.revision_id,
        "portfolio-engine-1",
        step.as_of_date,
        step.as_of_date,
        {},
        "abc123",
    )

    result = run(
        PortfolioState(Money("1000")),
        PortfolioPolicy(1, 40, Decimal("0.5")),
        (step,),
        manifest,
        fill_model,
    )

    assert result.fills[0].price == Decimal("101.00")
    assert result.fills[0].fee > 0
    assert result.starting_equity == Decimal(1000)
    assert result.metrics["total_return"] < Decimal("0.05")


def test_backtest_xirr_includes_dated_external_cash_flow():
    result = BacktestResult(
        uuid4(),
        (),
        (),
        ((date(2026, 1, 1), Decimal(100)), (date(2027, 1, 1), Decimal(250))),
        PortfolioState(Money("250")),
        Decimal(100),
        None,
        ((date(2026, 7, 1), Decimal(-100)),),
    )
    assert result.metrics["xirr"] > 0
    assert result.metrics["xirr"] != result.metrics["cagr"]
