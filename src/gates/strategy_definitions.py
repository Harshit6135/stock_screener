"""Gate adapter that injects indicator validation into strategy definitions."""

from pathlib import Path

from src.domains.indicators import PandasTaAdapter
from src.domains.strategies.api import StrategyDefinitions as _StrategyDefinitions
from src.gates.strategy_validation import StrategyIndicatorValidator


class StrategyDefinitions(_StrategyDefinitions):
    def __init__(self, database: str | Path, indicators: PandasTaAdapter) -> None:
        super().__init__(database, StrategyIndicatorValidator(indicators))


__all__ = ["StrategyDefinitions"]
