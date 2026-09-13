"""Isolated in-memory replay with explicit, publishable run provenance."""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, freeze_value
from src.portfolio_engine import (
    Candidate,
    Decision,
    DecisionType,
    ExecutionAssumptions,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
    evaluate,
)

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class FillModelRevision:
    revision_id: UUID
    semantic_version: str
    signal_timing: str = "close"
    execution_timing: str = "next_tradable_open"
    slippage_bps: Decimal = Decimal(0)
    fee_bps: Decimal = Decimal(0)
    tax_bps: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        slippage = Decimal(str(self.slippage_bps))
        fee = Decimal(str(self.fee_bps))
        tax = Decimal(str(self.tax_bps))
        if (
            not _SEMVER.fullmatch(self.semantic_version)
            or self.signal_timing != "close"
            or self.execution_timing != "next_tradable_open"
            or not slippage.is_finite()
            or not fee.is_finite()
            or not tax.is_finite()
            or slippage < 0
            or fee < 0
            or slippage >= 10_000
            or fee >= 10_000
            or tax < 0
            or tax >= 10_000
        ):
            raise DomainValidationError("fill model is invalid")
        object.__setattr__(self, "slippage_bps", slippage)
        object.__setattr__(self, "fee_bps", fee)
        object.__setattr__(self, "tax_bps", tax)

    def execution_assumptions(self) -> ExecutionAssumptions:
        return ExecutionAssumptions(self.slippage_bps, self.fee_bps, self.tax_bps)


@dataclass(frozen=True)
class BacktestRunManifest:
    run_id: UUID
    market_snapshot_ids: tuple[str, ...]
    strategy_revision_id: UUID
    policy_revision_id: UUID
    fill_model_revision_id: UUID
    engine_revision: str
    start_date: date
    end_date: date
    parameters: Mapping[str, str]
    code_revision: str

    def __post_init__(self) -> None:
        if (
            not self.market_snapshot_ids
            or len(set(self.market_snapshot_ids)) != len(self.market_snapshot_ids)
            or any(not value for value in self.market_snapshot_ids)
            or not self.engine_revision
            or not self.code_revision
            or self.end_date < self.start_date
        ):
            raise DomainValidationError("backtest run manifest is incomplete")
        object.__setattr__(self, "parameters", freeze_value(dict(self.parameters)))

    @property
    def fingerprint(self) -> str:
        body = json.dumps(
            {
                "market_snapshot_ids": self.market_snapshot_ids,
                "strategy_revision_id": str(self.strategy_revision_id),
                "policy_revision_id": str(self.policy_revision_id),
                "fill_model_revision_id": str(self.fill_model_revision_id),
                "engine_revision": self.engine_revision,
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
                "parameters": dict(self.parameters),
                "code_revision": self.code_revision,
            },
            sort_keys=True,
        ).encode()
        return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class BacktestStep:
    as_of_date: date
    candidates: tuple[Candidate, ...]
    bars: Mapping[str, MarketBar]
    regime: str = "RISK_ON"


@dataclass(frozen=True)
class SimulatedFill:
    as_of_date: date
    decision_type: DecisionType
    instrument_id: str
    units: int
    price: Decimal
    side: str
    fee: Decimal
    currency: str


@dataclass(frozen=True)
class BacktestResult:
    run_id: UUID
    decisions: tuple[Decision, ...]
    fills: tuple[SimulatedFill, ...]
    equity_curve: tuple[tuple[date, Decimal], ...]
    final_state: PortfolioState
    starting_equity: Decimal | None = None
    manifest: BacktestRunManifest | None = None
    cash_flows: tuple[tuple[date, Decimal], ...] = ()

    @staticmethod
    def _xirr(flows: tuple[tuple[date, Decimal], ...]) -> Decimal:
        if not flows or not any(amount < 0 for _, amount in flows) or not any(amount > 0 for _, amount in flows):
            return Decimal(0)
        origin = flows[0][0]
        rate = Decimal("0.1")
        for _ in range(50):
            value = Decimal(0)
            derivative = Decimal(0)
            for day, amount in flows:
                years = Decimal((day - origin).days) / Decimal(365)
                discount = (Decimal(1) + rate) ** years
                value += amount / discount
                if years:
                    derivative -= years * amount / (discount * (Decimal(1) + rate))
            if abs(value) < Decimal("0.0000001"):
                return rate
            if not derivative:
                break
            candidate = rate - value / derivative
            if candidate <= Decimal("-0.999999") or not candidate.is_finite():
                break
            rate = candidate
        return Decimal(0)

    @property
    def metrics(self) -> dict[str, Decimal]:
        if not self.equity_curve:
            return {key: Decimal(0) for key in (
                "total_return", "max_drawdown", "cagr", "xirr", "sharpe", "sortino", "calmar",
                "win_rate", "profit_factor", "expectancy", "average_holding_days",
            )}
        starting = (
            self.starting_equity if self.starting_equity is not None else self.equity_curve[0][1]
        )
        peak = starting
        drawdown = Decimal(0)
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak:
                drawdown = min(drawdown, (equity / peak) - Decimal(1))
        total_return = (self.equity_curve[-1][1] / starting) - Decimal(1) if starting else Decimal(0)
        years = Decimal(max((self.equity_curve[-1][0] - self.equity_curve[0][0]).days, 1)) / Decimal(365)
        cagr = (self.equity_curve[-1][1] / starting) ** (Decimal(1) / years) - Decimal(1) if starting > 0 else Decimal(0)
        xirr = self._xirr(
            ((self.equity_curve[0][0], -starting), *self.cash_flows,
             (self.equity_curve[-1][0], self.equity_curve[-1][1]))
        )
        returns = [self.equity_curve[index][1] / self.equity_curve[index - 1][1] - 1
                   for index in range(1, len(self.equity_curve)) if self.equity_curve[index - 1][1]]
        average = sum(returns, Decimal(0)) / len(returns) if returns else Decimal(0)
        variance = sum((item - average) ** 2 for item in returns) / len(returns) if returns else Decimal(0)
        deviation = variance.sqrt() if variance else Decimal(0)
        downside = [min(item, Decimal(0)) ** 2 for item in returns]
        downside_deviation = (sum(downside, Decimal(0)) / len(downside)).sqrt() if downside else Decimal(0)
        trades = self.completed_trades
        profits = [item["pnl"] for item in trades]
        gross_profit = sum((item for item in profits if item > 0), Decimal(0))
        gross_loss = -sum((item for item in profits if item < 0), Decimal(0))
        trade_count = len(profits)
        return {
            "total_return": total_return,
            "max_drawdown": drawdown,
            "cagr": cagr,
            "xirr": xirr,
            "sharpe": average / deviation * Decimal(252).sqrt() if deviation else Decimal(0),
            "sortino": average / downside_deviation * Decimal(252).sqrt() if downside_deviation else Decimal(0),
            "calmar": cagr / abs(drawdown) if drawdown else Decimal(0),
            "win_rate": Decimal(sum(item > 0 for item in profits)) / trade_count if trade_count else Decimal(0),
            "profit_factor": gross_profit / gross_loss if gross_loss else (Decimal("Infinity") if gross_profit else Decimal(0)),
            "expectancy": sum(profits, Decimal(0)) / trade_count if trade_count else Decimal(0),
            "average_holding_days": sum((item["holding_days"] for item in trades), Decimal(0)) / trade_count if trade_count else Decimal(0),
        }

    @property
    def completed_trades(self) -> tuple[dict[str, object], ...]:
        """FIFO close pairs, excluding positions still open at the report end."""
        lots: dict[str, list[dict[str, object]]] = defaultdict(list)
        trades: list[dict[str, object]] = []
        for fill in self.fills:
            if fill.side == "BUY":
                lots[fill.instrument_id].append({"date": fill.as_of_date, "units": fill.units,
                                                  "unit_cost": fill.price + (fill.fee / fill.units if fill.units else Decimal(0))})
                continue
            remaining = fill.units
            unit_proceeds = fill.price - (fill.fee / fill.units if fill.units else Decimal(0))
            while remaining and lots[fill.instrument_id]:
                lot = lots[fill.instrument_id][0]
                matched = min(remaining, int(lot["units"]))
                pnl = (unit_proceeds - Decimal(str(lot["unit_cost"]))) * matched
                trades.append({
                    "instrument_id": fill.instrument_id,
                    "buy_date": lot["date"],
                    "sell_date": fill.as_of_date,
                    "units": matched,
                    "pnl": pnl,
                    "holding_days": Decimal((fill.as_of_date - lot["date"]).days),
                })
                remaining -= matched
                lot["units"] = int(lot["units"]) - matched
                if lot["units"] == 0:
                    lots[fill.instrument_id].pop(0)
        return tuple(trades)

    @property
    def annual_returns(self) -> dict[str, Decimal]:
        by_year: dict[str, tuple[Decimal, Decimal]] = {}
        for day, value in self.equity_curve:
            year = str(day.year)
            if year not in by_year:
                by_year[year] = (value, value)
            else:
                by_year[year] = (by_year[year][0], value)
        return {year: (end / start - 1 if start else Decimal(0)) for year, (start, end) in by_year.items()}

    @property
    def trade_counts(self) -> dict[str, int]:
        return {
            "buy": sum(fill.side == "BUY" for fill in self.fills),
            "sell": sum(fill.side == "SELL" for fill in self.fills),
            "pyramid": sum(fill.decision_type == DecisionType.PYRAMID_ADD for fill in self.fills),
        }

    @property
    def sanity_flags(self) -> list[str]:
        metrics = self.metrics
        flags: list[str] = []
        if metrics["sharpe"] > Decimal(5):
            flags.append("sharpe_above_5")
        if metrics["max_drawdown"] == 0 and len(self.equity_curve) > 2:
            flags.append("zero_drawdown")
        if not self.fills:
            flags.append("no_fills")
        if len(self.final_state.holdings) == 1 and self.final_state.holdings:
            flags.append("single_position_concentration")
        return flags

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        if self.manifest is None:
            raise DomainValidationError(
                "backtest result requires a run manifest before publication"
            )
        return store.publish_json(
            "runs/backtests",
            str(self.run_id),
            self.to_payload(),
            upstream_ids=self.upstream_ids,
        )

    @property
    def upstream_ids(self) -> tuple[str, ...]:
        if self.manifest is None:
            raise DomainValidationError("backtest result requires a run manifest")
        return self.manifest.market_snapshot_ids + (
            str(self.manifest.strategy_revision_id),
            str(self.manifest.policy_revision_id),
            str(self.manifest.fill_model_revision_id),
        )

    def to_payload(self) -> dict[str, object]:
        if self.manifest is None:
            raise DomainValidationError("backtest result requires a run manifest")
        return {
            "run_id": str(self.run_id),
            "manifest": asdict(self.manifest),
            "fingerprint": self.manifest.fingerprint,
            "decisions": [asdict(item) for item in self.decisions],
            "fills": [asdict(item) for item in self.fills],
            "equity_curve": [{"date": item[0], "value": item[1]} for item in self.equity_curve],
            "metrics": self.metrics,
            "annual_returns": self.annual_returns,
            "trade_counts": self.trade_counts,
            "trade_log": [asdict(item) for item in self.fills],
            "open_positions": [asdict(item) for item in self.final_state.holdings],
            "open_position_treatment": "marked_to_market_at_end_date",
            "sanity_flags": self.sanity_flags,
            "starting_equity": self.starting_equity,
            "cash_flows": [{"date": day, "amount": amount} for day, amount in self.cash_flows],
            "final_cash": self.final_state.cash.amount,
        }


_SELLS = {
    DecisionType.SELL,
    DecisionType.SWAP_SELL,
    DecisionType.HARD_STOP_GAP_OPEN,
    DecisionType.HARD_STOP_INTRADAY,
    DecisionType.SCORE_EXIT,
}


def run(
    initial_state: PortfolioState,
    policy: PortfolioPolicy,
    steps: tuple[BacktestStep, ...],
    manifest: BacktestRunManifest | None = None,
    fill_model: FillModelRevision | None = None,
    cash_flows: tuple[tuple[date, Decimal], ...] = (),
) -> BacktestResult:
    dates = tuple(step.as_of_date for step in steps)
    if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
        raise DomainValidationError("backtest steps must be strictly chronological")
    if manifest and (
        not dates or manifest.start_date != dates[0] or manifest.end_date != dates[-1]
    ):
        raise DomainValidationError("backtest manifest date range does not match steps")
    if manifest and (
        fill_model is None or manifest.fill_model_revision_id != fill_model.revision_id
    ):
        raise DomainValidationError("backtest fill model does not match its manifest")
    if any(day < dates[0] or day > dates[-1] for day, _ in cash_flows) if dates else cash_flows:
        raise DomainValidationError("backtest cash flows must be within the replay range")
    fill_model = fill_model or FillModelRevision(uuid4(), "1.0.0")
    state = initial_state
    all_decisions: list[Decision] = []
    fills: list[SimulatedFill] = []
    equity_curve: list[tuple[date, Decimal]] = []
    first_rebalance_day = dates[0] if dates else None
    rebalance_months: set[tuple[int, int]] = set()
    starting_equity = initial_state.cash.amount
    if steps:
        for holding in initial_state.holdings:
            bar = steps[0].bars.get(holding.instrument_id)
            if bar is None:
                raise DomainValidationError(
                    f"missing opening valuation bar for {holding.instrument_id}"
                )
            starting_equity += bar.open * holding.units.units
    for step in steps:
        rebalance = (
            policy.rebalance_frequency == "DAILY"
            or first_rebalance_day is not None
            and (
                policy.rebalance_frequency == "BIWEEKLY"
                and (step.as_of_date - first_rebalance_day).days % 14 == 0
                or policy.rebalance_frequency == "MONTHLY"
                and (step.as_of_date.year, step.as_of_date.month) not in rebalance_months
            )
        )
        if rebalance:
            rebalance_months.add((step.as_of_date.year, step.as_of_date.month))
        candidates = step.candidates if (rebalance or policy.mid_week_buy) and step.regime == "RISK_ON" else ()
        decisions, state = evaluate(
            state,
            policy,
            candidates,
            step.bars,
            fill_model.execution_assumptions(),
            is_rebalance_day=rebalance,
        )
        all_decisions.extend(decisions)
        for decision in decisions:
            if decision.instrument_id and decision.units and decision.execution_price:
                fills.append(
                    SimulatedFill(
                        step.as_of_date,
                        decision.type,
                        decision.instrument_id,
                        decision.units.units,
                        decision.execution_price.amount,
                        "SELL" if decision.type in _SELLS else "BUY",
                        decision.fee.amount,
                        decision.execution_price.currency,
                    )
                )
        value = state.cash.amount
        for holding in state.holdings:
            bar = step.bars.get(holding.instrument_id)
            if bar is None:
                raise DomainValidationError(f"missing valuation bar for {holding.instrument_id}")
            value += bar.close * holding.units.units
        equity_curve.append((step.as_of_date, value))
    return BacktestResult(
        manifest.run_id if manifest else uuid4(),
        tuple(all_decisions),
        tuple(fills),
        tuple(equity_curve),
        state,
        starting_equity,
        manifest,
        tuple((day, Decimal(str(amount))) for day, amount in cash_flows),
    )
