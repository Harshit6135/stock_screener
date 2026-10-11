"""Tests for strategy-domain ranking patterns."""

import pytest

from src.domains.strategies.ranking_patterns import (
    DirectSignalRanking,
    FactorPercentileRanking,
    ranking_pattern_for,
)


def test_factor_percentile_ranking_basic():
    pattern = FactorPercentileRanking()
    assert pattern.pattern_name == "factor_percentile"
    features = {
        "a": {"trend": 10, "momentum": 5},
        "b": {"trend": 20, "momentum": 10},
        "c": {"trend": 15, "momentum": 8},
    }
    weights = {"trend": 0.6, "momentum": 0.4}
    ranked = pattern.rank(
        features, factor_weights=weights, symbols={"a": "AAA", "b": "BBB", "c": "CCC"}
    )
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
    ranked = pattern.rank(
        features, signal_rules=rules, symbols={"a": "AAA", "b": "BBB", "c": "CCC", "d": "DDD"}
    )
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


def test_factor_percentile_ranking_stages():
    """Stage A: raw indicators, Stage B: percentiles, Stage C: weighted rank."""
    pattern = FactorPercentileRanking()
    features = {
        "a": {"trend": 10, "momentum": 20},
        "b": {"trend": 30, "momentum": 10},
    }
    weights = {"trend": 0.5, "momentum": 0.5}
    ranked = pattern.rank(features, factor_weights=weights, symbols={"a": "AAA", "b": "BBB"})
    # Both should have percentiles computed
    for item in ranked:
        assert "percentiles" in item
        assert "trend" in item["percentiles"]
        assert "momentum" in item["percentiles"]
    assert ranked[0]["composite_score"] >= ranked[1]["composite_score"]


def test_direct_signal_ordering_adx_then_adtv():
    pattern = DirectSignalRanking()
    features = {
        "a": {"signal": "BUY", "adx": 30, "adtv": 500_000_000},
        "b": {"signal": "BUY", "adx": 30, "adtv": 200_000_000},
    }
    rules = {"adx_minimum": 25, "minimum_adtv": 100_000_000}
    ranked = pattern.rank(features, signal_rules=rules, symbols={"a": "A", "b": "B"})
    assert ranked[0]["instrument_id"] == "a"
