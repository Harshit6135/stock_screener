from pathlib import Path

import pytest

from src.domains.indicators.registry import PandasTaAdapter
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.platform_kernel import DomainValidationError


def _strategies_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "strategies"


def _runtime(database) -> StrategyRuntime:
    return StrategyRuntime(StrategyDefinitions(database, PandasTaAdapter()))


def test_named_yaml_files_exist():
    strategies_dir = _strategies_dir()
    assert (strategies_dir / "momentum.yml").is_file()
    assert (strategies_dir / "positional_trend_following.yml").is_file()


def test_seed_exposes_only_canonical_strategies_and_is_idempotent(tmp_path):
    runtime = _runtime(tmp_path / "system.db")
    runtime.seed(_strategies_dir())
    runtime.seed(_strategies_dir())
    strategy_ids = runtime.strategy_ids()
    assert set(strategy_ids) == {"momentum", "positional_trend_following"}
    assert len(strategy_ids) == len(set(strategy_ids))


def test_revision_requires_canonical_strategy_id(tmp_path):
    runtime = _runtime(tmp_path / "system.db")
    runtime.seed(_strategies_dir())
    assert runtime.revision("momentum") is not None
    with pytest.raises(DomainValidationError, match="has no active revision"):
        runtime.revision("strategy1")


def test_strategy_kind_momentum_is_factor_score(tmp_path):
    runtime = _runtime(tmp_path / "system.db")
    runtime.seed(_strategies_dir())
    assert runtime.strategy_kind("momentum") == "factor_score"


def test_strategy_kind_positional_is_event_signal(tmp_path):
    runtime = _runtime(tmp_path / "system.db")
    runtime.seed(_strategies_dir())
    assert runtime.strategy_kind("positional_trend_following") == "event_signal"


def test_factor_weights_momentum(tmp_path):
    runtime = _runtime(tmp_path / "system.db")
    runtime.seed(_strategies_dir())
    weights = runtime.factor_weights("momentum")
    assert set(weights) == {"trend", "momentum", "efficiency", "volume", "structure"}
    assert abs(sum(weights.values()) - 1.0) < 1e-9
