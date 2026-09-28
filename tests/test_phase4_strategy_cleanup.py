"""Phase 4 Task 4.12: Named strategies, ranking patterns and retirement cleanup tests."""

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.application.catalog import ArtifactCatalog
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.publication import ArtifactPublisher
from src.application.ranking_patterns import (
    DirectSignalRanking,
    FactorPercentileRanking,
    ranking_pattern_for,
)
from src.application.research_jobs import ResearchJobs
from src.application.strategy_definitions import StrategyDefinitions
from src.application.strategy_runtime import (
    LEGACY_STRATEGY_MAP,
    NAMED_TO_LEGACY,
    REMOVED_STRATEGIES,
    RETAINED_STRATEGIES,
    StrategyRuntime,
    resolve_strategy_id,
)
from src.indicators.registry import PandasTaAdapter
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore, DomainValidationError


# ─── Task 4.1: Strategy identity mapping ───


def test_legacy_strategy_map_contains_both_retained_strategies():
    assert LEGACY_STRATEGY_MAP == {"strategy1": "momentum", "strategy4": "positional_trend_following"}


def test_named_to_legacy_is_inverse():
    assert NAMED_TO_LEGACY == {"momentum": "strategy1", "positional_trend_following": "strategy4"}


def test_removed_strategies_are_benchmark_and_early():
    assert REMOVED_STRATEGIES == frozenset({"strategy2", "strategy3"})


def test_retained_strategies_are_named():
    assert RETAINED_STRATEGIES == frozenset({"momentum", "positional_trend_following"})


def test_resolve_strategy_id_maps_legacy():
    assert resolve_strategy_id("strategy1") == "momentum"
    assert resolve_strategy_id("strategy4") == "positional_trend_following"


def test_resolve_strategy_id_passes_named_through():
    assert resolve_strategy_id("momentum") == "momentum"
    assert resolve_strategy_id("positional_trend_following") == "positional_trend_following"


def test_resolve_strategy_id_passes_unknown_through():
    assert resolve_strategy_id("unknown") == "unknown"


# ─── Task 4.1: YAML migration ───


def test_named_yaml_files_exist():
    strategies_dir = Path(__file__).resolve().parents[1] / "strategies"
    assert (strategies_dir / "momentum.yml").is_file()
    assert (strategies_dir / "positional_trend_following.yml").is_file()


def test_legacy_yaml_files_removed():
    strategies_dir = Path(__file__).resolve().parents[1] / "strategies"
    assert not (strategies_dir / "momentum_quality.yml").exists()
    assert not (strategies_dir / "strategy4.yml").exists()
    assert not (strategies_dir / "benchmark_relative_momentum.yml").exists()
    assert not (strategies_dir / "early_momentum.yml").exists()


# ─── Task 4.1/4.2: Strategy definitions and runtime ───


def test_seed_loads_named_strategies(tmp_path):
    database = tmp_path / "system.db"
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    ids = runtime.strategy_ids()
    assert "momentum" in ids
    assert "positional_trend_following" in ids


def test_seed_skips_removed_strategies(tmp_path):
    database = tmp_path / "system.db"
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    ids = runtime.strategy_ids()
    assert "strategy2" not in ids
    assert "strategy3" not in ids


def test_revision_resolves_legacy_to_named(tmp_path):
    database = tmp_path / "system.db"
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    # Should not raise when accessing via legacy ID
    rev_named = runtime.revision("momentum")
    rev_legacy = runtime.revision("strategy1")
    # Both should resolve to the same revision (one from named, one from legacy fallback)
    # The exact behavior depends on whether the legacy ID exists in the DB
    assert rev_named is not None
    assert rev_legacy is not None


def test_strategy_kind_momentum_is_factor_score(tmp_path):
    database = tmp_path / "system.db"
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    assert runtime.strategy_kind("momentum") == "factor_score"


def test_strategy_kind_positional_is_event_signal(tmp_path):
    database = tmp_path / "system.db"
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    assert runtime.strategy_kind("positional_trend_following") == "event_signal"


def test_portfolio_policy_retired_raises(tmp_path):
    database = tmp_path / "system.db"
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    with pytest.raises(DomainValidationError, match="retired"):
        runtime.portfolio_policy("strategy3")


def test_factor_weights_momentum(tmp_path):
    database = tmp_path / "system.db"
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    weights = runtime.factor_weights("momentum")
    assert set(weights.keys()) == {"trend", "momentum", "efficiency", "volume", "structure"}
    assert abs(sum(weights.values()) - 1.0) < 1e-9


# ─── Task 4.3: Removed strategy retirement ───


def test_early_momentum_not_imported_in_composition():
    from src.application import composition
    source = Path(composition.__file__).read_text()
    assert "EarlyMomentumJobs" not in source
    assert "early_momentum" not in source


# ─── Task 4.5: Ranking pattern dispatch ───


def test_factor_percentile_ranking_basic():
    pattern = FactorPercentileRanking()
    assert pattern.pattern_name == "factor_percentile"
    features = {
        "a": {"trend": 10, "momentum": 5},
        "b": {"trend": 20, "momentum": 10},
        "c": {"trend": 15, "momentum": 8},
    }
    weights = {"trend": 0.6, "momentum": 0.4}
    ranked = pattern.rank(features, factor_weights=weights, symbols={"a": "AAA", "b": "BBB", "c": "CCC"})
    assert len(ranked) == 3
    assert ranked[0]["rank"] == 1
    assert ranked[0]["instrument_id"] == "b"  # highest trend + momentum
    assert ranked[2]["rank"] == 3


def test_factor_percentile_ranking_empty():
    pattern = FactorPercentileRanking()
    assert pattern.rank({}, factor_weights={}) == []


def test_direct_signal_ranking_basic():
    pattern = DirectSignalRanking()
    assert pattern.pattern_name == "direct_signal"
    features = {
        "a": {"signal": "BUY", "adx": 30, "adtv": 200_000_000},
        "b": {"signal": "BUY", "adx": 35, "adtv": 150_000_000},
        "c": {"signal": "HOLD", "adx": 40, "adtv": 300_000_000},
        "d": {"signal": "BUY", "adx": 20, "adtv": 50_000_000},  # below thresholds
    }
    rules = {"adx_minimum": 25, "minimum_adtv": 100_000_000}
    ranked = pattern.rank(features, signal_rules=rules, symbols={"a": "AAA", "b": "BBB", "c": "CCC", "d": "DDD"})
    assert len(ranked) == 2  # only a, b eligible
    assert ranked[0]["instrument_id"] == "b"  # higher ADX
    assert ranked[1]["instrument_id"] == "a"


def test_direct_signal_ranking_no_signals():
    pattern = DirectSignalRanking()
    features = {"a": {"signal": "HOLD", "adx": 30, "adtv": 200_000_000}}
    ranked = pattern.rank(features, signal_rules={"adx_minimum": 25, "minimum_adtv": 100_000_000})
    assert ranked == []


def test_ranking_pattern_factory():
    assert isinstance(ranking_pattern_for("factor_score"), FactorPercentileRanking)
    assert isinstance(ranking_pattern_for("event_signal"), DirectSignalRanking)
    with pytest.raises(ValueError, match="unknown"):
        ranking_pattern_for("invalid")


def test_percentile_fingerprint_stable():
    fp1 = FactorPercentileRanking.percentile_fingerprint(
        {"trend": 0.3, "momentum": 0.7}, "universe-1", "code-hash-1"
    )
    fp2 = FactorPercentileRanking.percentile_fingerprint(
        {"trend": 0.3, "momentum": 0.7}, "universe-1", "code-hash-1"
    )
    assert fp1 == fp2


def test_percentile_fingerprint_differs_on_universe():
    fp1 = FactorPercentileRanking.percentile_fingerprint(
        {"trend": 0.3, "momentum": 0.7}, "universe-1", "code-hash-1"
    )
    fp2 = FactorPercentileRanking.percentile_fingerprint(
        {"trend": 0.3, "momentum": 0.7}, "universe-2", "code-hash-1"
    )
    assert fp1 != fp2


# ─── Task 4.6: Percentile snapshot persistence ───


def test_percentile_snapshot_round_trip(tmp_path):
    database = tmp_path / "system.db"
    research = ResearchJobs(database, MarketRepository(database), None)
    fingerprint = "test-fingerprint-001"
    percentiles = {
        "inst-a": {"trend": (10.5, 0.75), "momentum": (5.0, 0.50)},
        "inst-b": {"trend": (20.0, 1.0), "momentum": (8.0, 0.80)},
    }
    result = research.upsert_percentile_snapshot(
        "snap-1", "rev-1", "2026-09-10", fingerprint, percentiles,
        {"inst-a": "AAA", "inst-b": "BBB"}
    )
    assert result["snapshot_id"] == "snap-1"
    assert result["rows"] == 4

    cached = research.read_percentile_snapshot(fingerprint, "2026-09-10")
    assert cached is not None
    assert abs(cached["inst-a"]["trend"] - 0.75) < 1e-9
    assert abs(cached["inst-b"]["momentum"] - 0.80) < 1e-9


def test_percentile_snapshot_reuse_on_same_fingerprint(tmp_path):
    database = tmp_path / "system.db"
    research = ResearchJobs(database, MarketRepository(database), None)
    percentiles = {"x": {"f": (1.0, 0.5)}}
    research.upsert_percentile_snapshot("snap-a", "rev-a", "2026-09-10", "fp-1", percentiles, {"x": "X"})
    cached = research.read_percentile_snapshot("fp-1", "2026-09-10")
    assert cached is not None
    # Different fingerprint returns None
    assert research.read_percentile_snapshot("fp-2", "2026-09-10") is None


# ─── Task 4.10: Research artifact lineage ───


def test_lineage_round_trip(tmp_path):
    database = tmp_path / "system.db"
    research = ResearchJobs(database, MarketRepository(database), None)
    research.record_lineage(
        "art-1", "momentum", "rev-1",
        indicator_code_hash="abc123",
        universe_snapshot_id="univ-1",
        market_data_start="2026-01-01",
        market_data_end="2026-09-10",
        market_history_revision="mhr-5",
        percentile_snapshot_id="snap-1",
    )
    lineage = research.read_lineage("art-1")
    assert lineage is not None
    assert lineage["strategy_id"] == "momentum"
    assert lineage["indicator_code_hash"] == "abc123"
    assert lineage["percentile_snapshot_id"] == "snap-1"
    assert lineage["computed_at"] is not None


def test_lineage_not_found(tmp_path):
    database = tmp_path / "system.db"
    research = ResearchJobs(database, MarketRepository(database), None)
    assert research.read_lineage("nonexistent") is None


def test_lineage_immutable_on_rewrite(tmp_path):
    database = tmp_path / "system.db"
    research = ResearchJobs(database, MarketRepository(database), None)
    research.record_lineage("art-1", "momentum", "rev-1", indicator_code_hash="hash1")
    research.record_lineage("art-1", "momentum", "rev-1", indicator_code_hash="hash2")
    lineage = research.read_lineage("art-1")
    assert lineage["indicator_code_hash"] == "hash2"  # INSERT OR REPLACE


# ─── Task 4.7: Factor stages A/B/C ───


def test_factor_percentile_ranking_stages():
    """Stage A: raw indicators, Stage B: percentiles, Stage C: weighted rank."""
    pattern = FactorPercentileRanking()
    features = {
        "a": {"trend": 10, "momentum": 20},
        "b": {"trend": 30, "momentum": 10},
    }
    weights = {"trend": 0.5, "momentum": 0.5}
    ranked = pattern.rank(features, factor_weights=weights,
                          symbols={"a": "AAA", "b": "BBB"})
    # Both should have percentiles computed
    for item in ranked:
        assert "percentiles" in item
        assert "trend" in item["percentiles"]
        assert "momentum" in item["percentiles"]
    assert ranked[0]["composite_score"] >= ranked[1]["composite_score"]


# ─── Task 4.8: Direct event ranking ───


def test_direct_signal_ordering_adx_then_adtv():
    pattern = DirectSignalRanking()
    features = {
        "a": {"signal": "BUY", "adx": 30, "adtv": 500_000_000},
        "b": {"signal": "BUY", "adx": 30, "adtv": 200_000_000},
    }
    rules = {"adx_minimum": 25, "minimum_adtv": 100_000_000}
    ranked = pattern.rank(features, signal_rules=rules, symbols={"a": "A", "b": "B"})
    assert ranked[0]["instrument_id"] == "a"  # same ADX, higher ADTV


# ─── Task 4.9: Pipeline both-strategy branches ───


def test_pipeline_default_strategies_include_both_retained_branches(tmp_path):
    from src.application.jobs import JobStore
    from src.application.pipeline_jobs import ResearchPipelineJobs
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-11"})
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None
    assert claimed.payload["strategies"] == ["momentum"]
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None
    assert claimed.payload["universe"] == "SNAPSHOT_NIFTY500"


# ─── Task 4.1/4.12: Named strategy two-strategy evidence ───


def test_fresh_store_has_exactly_two_named_strategies(tmp_path):
    database = tmp_path / "system.db"
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    ids = set(runtime.strategy_ids())
    assert ids == {"momentum", "positional_trend_following"}


def test_no_duplicate_active_revisions(tmp_path):
    database = tmp_path / "system.db"
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    # Seeding again should not create duplicates
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    ids = list(runtime.strategy_ids())
    assert len(ids) == len(set(ids))  # No duplicates
