import pandas as pd

from src.application.strategy_definitions import StrategyDefinitions
from src.indicators.registry import PandasTaAdapter


def test_pandas_ta_catalogue_and_ema_are_safe_and_deterministic():
    adapter = PandasTaAdapter()
    assert {item["indicator_key"] for item in adapter.catalogue()} >= {"ema", "rsi", "atr", "macd"}
    close = pd.Series([float(value) for value in range(1, 40)])
    first = adapter.calculate("ema", {"close": close}, {"length": 10})
    second = adapter.calculate("ema", {"close": close}, {"length": 10})
    assert first.equals(second)
    assert first.index.equals(close.index)
    assert first.iloc[:9].isna().all().all()


def test_yaml_strategy_revision_is_immutable_and_activation_retires_previous(tmp_path):
    strategies = StrategyDefinitions(tmp_path / "strategies.db", PandasTaAdapter())
    template = """schema_version: 1
strategy:
  id: momentum_quality
  name: Momentum Quality
  version: %s
calculation:
  instrument_implementation: custom.momentum_quality_features
  required_sessions: 200
factors:
  trend: 0.30
  momentum: 0.25
  efficiency: 0.20
  volume: 0.15
  structure: 0.10
portfolio_policy:
  initial_capital: 100000
  max_positions: 15
  exit_threshold: 40
  buffer_percent: 0.25
  max_concentration_pct: 0.25
ranking:
  frequency: weekly
  session: last_trading_session
"""
    first = strategies.create_from_yaml(template % "1.0.0")
    second = strategies.create_from_yaml(template % "1.0.1")
    assert first["status"] == "VALIDATED"
    assert strategies.activate(first["revision_id"])["status"] == "ACTIVE"
    assert strategies.activate(second["revision_id"])["status"] == "ACTIVE"
    assert strategies.get(first["revision_id"])["status"] == "RETIRED"
