"""Isolated in-memory replay with explicit, publishable run provenance."""

import hashlib
import json
import re
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

    def __post_init__(self) -> None:
        slippage = Decimal(str(self.slippage_bps))
        fee = Decimal(str(self.fee_bps))
        if (
            not _SEMVER.fullmatch(self.semantic_version)
            or self.signal_timing != "close"
            or self.execution_timing != "next_tradable_open"
            or not slippage.is_finite()
            or not fee.is_finite()
            or slippage < 0
            or fee < 0
            or slippage >= 10_000
            or fee >= 10_000
        ):
            raise DomainValidationError("fill model is invalid")
        object.__setattr__(self, "slippage_bps", slippage)
        object.__setattr__(self, "fee_bps", fee)

    def execution_assumptions(self) -> ExecutionAssumptions:
        return ExecutionAssumptions(self.slippage_bps, self.fee_bps)


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

    @property
    def metrics(self) -> dict[str, Decimal]:
        if not self.equity_curve:
            return {"total_return": Decimal(0), "max_drawdown": Decimal(0)}
        starting = (
            self.starting_equity if self.starting_equity is not None else self.equity_curve[0][1]
        )
        peak = starting
        drawdown = Decimal(0)
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak:
                drawdown = min(drawdown, (equity / peak) - Decimal(1))
        return {
            "total_return": (self.equity_curve[-1][1] / starting) - Decimal(1)
            if starting
            else Decimal(0),
            "max_drawdown": drawdown,
        }

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
            "starting_equity": self.starting_equity,
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
    fill_model = fill_model or FillModelRevision(uuid4(), "1.0.0")
    state = initial_state
    all_decisions: list[Decision] = []
    fills: list[SimulatedFill] = []
    equity_curve: list[tuple[date, Decimal]] = []
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
        decisions, state = evaluate(
            state,
            policy,
            step.candidates,
            step.bars,
            fill_model.execution_assumptions(),
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
    )
