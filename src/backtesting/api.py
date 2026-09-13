"""Isolated in-memory replay with explicit, publishable run provenance."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError
from src.portfolio_engine import Candidate, Decision, DecisionType, MarketBar, PortfolioPolicy, PortfolioState, evaluate


@dataclass(frozen=True)
class FillModelRevision:
    revision_id: UUID
    semantic_version: str
    signal_timing: str = "close"
    execution_timing: str = "next_tradable_open"
    slippage_bps: Decimal = Decimal("0")
    fee_bps: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.signal_timing != "close" or self.execution_timing != "next_tradable_open" or self.slippage_bps < 0 or self.fee_bps < 0:
            raise DomainValidationError("fill model is invalid")


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

    @property
    def fingerprint(self) -> str:
        body = json.dumps({"market_snapshot_ids": self.market_snapshot_ids, "strategy_revision_id": str(self.strategy_revision_id), "policy_revision_id": str(self.policy_revision_id), "fill_model_revision_id": str(self.fill_model_revision_id), "engine_revision": self.engine_revision, "start_date": self.start_date.isoformat(), "end_date": self.end_date.isoformat(), "parameters": dict(self.parameters), "code_revision": self.code_revision}, sort_keys=True).encode()
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


@dataclass(frozen=True)
class BacktestResult:
    run_id: UUID
    decisions: tuple[Decision, ...]
    fills: tuple[SimulatedFill, ...]
    equity_curve: tuple[tuple[date, Decimal], ...]
    final_state: PortfolioState
    manifest: BacktestRunManifest | None = None

    @property
    def metrics(self) -> dict[str, Decimal]:
        if not self.equity_curve:
            return {"total_return": Decimal("0"), "max_drawdown": Decimal("0")}
        starting = self.equity_curve[0][1]
        peak = starting
        drawdown = Decimal("0")
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak:
                drawdown = min(drawdown, (equity / peak) - Decimal("1"))
        return {"total_return": (self.equity_curve[-1][1] / starting) - Decimal("1") if starting else Decimal("0"), "max_drawdown": drawdown}

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        if self.manifest is None:
            raise DomainValidationError("backtest result requires a run manifest before publication")
        payload = {"run_id": str(self.run_id), "manifest": asdict(self.manifest), "fingerprint": self.manifest.fingerprint, "decisions": [asdict(item) for item in self.decisions], "fills": [asdict(item) for item in self.fills], "equity_curve": [{"date": item[0], "value": item[1]} for item in self.equity_curve], "metrics": self.metrics, "final_cash": self.final_state.cash.amount}
        return store.publish_json("runs/backtests", str(self.run_id), payload, upstream_ids=self.manifest.market_snapshot_ids + (str(self.manifest.strategy_revision_id), str(self.manifest.policy_revision_id), str(self.manifest.fill_model_revision_id)))


_SELLS = {DecisionType.SELL, DecisionType.SWAP_SELL, DecisionType.HARD_STOP_GAP_OPEN, DecisionType.HARD_STOP_INTRADAY, DecisionType.SCORE_EXIT}


def run(initial_state: PortfolioState, policy: PortfolioPolicy, steps: tuple[BacktestStep, ...], manifest: BacktestRunManifest | None = None) -> BacktestResult:
    dates = tuple(step.as_of_date for step in steps)
    if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
        raise DomainValidationError("backtest steps must be strictly chronological")
    if manifest and (not dates or manifest.start_date != dates[0] or manifest.end_date != dates[-1]):
        raise DomainValidationError("backtest manifest date range does not match steps")
    state = initial_state
    all_decisions: list[Decision] = []
    fills: list[SimulatedFill] = []
    equity_curve: list[tuple[date, Decimal]] = []
    for step in steps:
        decisions, state = evaluate(state, policy, step.candidates, step.bars)
        all_decisions.extend(decisions)
        for decision in decisions:
            if decision.instrument_id and decision.units and decision.execution_price:
                fills.append(SimulatedFill(step.as_of_date, decision.type, decision.instrument_id, decision.units.units, decision.execution_price.amount))
        value = state.cash.amount
        for holding in state.holdings:
            bar = step.bars.get(holding.instrument_id)
            if bar is None:
                raise DomainValidationError(f"missing valuation bar for {holding.instrument_id}")
            value += bar.close * holding.units.units
        equity_curve.append((step.as_of_date, value))
    return BacktestResult(manifest.run_id if manifest else uuid4(), tuple(all_decisions), tuple(fills), tuple(equity_curve), state, manifest)
