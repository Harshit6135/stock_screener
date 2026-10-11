"""Adapter connecting replay evaluation to the portfolio decision domain."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.domains.backtesting import BacktestExecutionAssumptions, FillModelRevision
from src.domains.portfolio_engine import ExecutionAssumptions, evaluate


class BacktestPortfolioEngineAdapter:
    """Translate neutral replay assumptions into portfolio-engine contracts."""

    def execution_assumptions(self, fill_model: FillModelRevision) -> ExecutionAssumptions:
        values: BacktestExecutionAssumptions = fill_model.execution_assumptions()
        return ExecutionAssumptions(values.slippage_bps, values.fee_bps, values.tax_bps)

    def evaluate(
        self,
        state: Any,
        policy: Any,
        candidates: Sequence[Any],
        bars: Mapping[str, Any],
        assumptions: object,
        *,
        is_rebalance_day: bool,
        score_candidates: Sequence[Any],
        forced_universe_exits: frozenset[str],
    ) -> tuple[Sequence[Any], Any]:
        return evaluate(
            state,
            policy,
            candidates,
            bars,
            assumptions,
            is_rebalance_day=is_rebalance_day,
            score_candidates=score_candidates,
            forced_universe_exits=forced_universe_exits,
        )
