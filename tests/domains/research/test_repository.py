"""Percentile snapshot and artifact lineage contracts for research jobs."""

import pytest

from src.domains.research import ResearchRepository
from src.platform_kernel import DomainValidationError


def _research_repository(tmp_path) -> ResearchRepository:
    database = tmp_path / "system.db"
    return ResearchRepository(database)


def test_percentile_snapshot_round_trip(tmp_path):
    research = _research_repository(tmp_path)
    fingerprint = "test-fingerprint-001"
    percentiles = {
        "inst-a": {"trend": (10.5, 0.75), "momentum": (5.0, 0.50)},
        "inst-b": {"trend": (20.0, 1.0), "momentum": (8.0, 0.80)},
    }
    result = research.upsert_percentile_snapshot(
        "snap-1",
        "rev-1",
        "2026-09-10",
        fingerprint,
        percentiles,
        {"inst-a": "AAA", "inst-b": "BBB"},
    )
    assert result["snapshot_id"] == "snap-1"
    assert result["rows"] == 4
    cached = research.read_percentile_snapshot(fingerprint, "2026-09-10")
    assert cached is not None
    assert abs(cached["inst-a"]["trend"] - 0.75) < 1e-9
    assert abs(cached["inst-b"]["momentum"] - 0.80) < 1e-9


def test_percentile_snapshot_lookup_uses_fingerprint(tmp_path):
    research = _research_repository(tmp_path)
    research.upsert_percentile_snapshot(
        "snap-a", "rev-a", "2026-09-10", "fp-1", {"x": {"f": (1.0, 0.5)}}, {"x": "X"}
    )
    assert research.read_percentile_snapshot("fp-1", "2026-09-10") is not None
    assert research.read_percentile_snapshot("fp-2", "2026-09-10") is None


def test_lineage_round_trip(tmp_path):
    research = _research_repository(tmp_path)
    research.record_lineage(
        "art-1",
        "momentum",
        "rev-1",
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
    assert _research_repository(tmp_path).read_lineage("nonexistent") is None


def test_lineage_immutable_on_rewrite(tmp_path):
    research = _research_repository(tmp_path)
    research.record_lineage("art-1", "momentum", "rev-1", indicator_code_hash="hash1")
    before = research.read_lineage("art-1")
    research.record_lineage("art-1", "momentum", "rev-1", indicator_code_hash="hash1")
    assert research.read_lineage("art-1") == before
    with pytest.raises(DomainValidationError, match="immutable"):
        research.record_lineage("art-1", "momentum", "rev-1", indicator_code_hash="hash2")
    assert research.read_lineage("art-1") == before


def test_daily_score_projection_replacement_and_date_upsert(tmp_path):
    repository = _research_repository(tmp_path)
    repository.replace_daily_score_range(
        "revision-1",
        "2026-09-10",
        "2026-09-11",
        [
            ("momentum", "revision-1", "2026-09-10", "inst-a", "AAA", 0.7, 1.0, "score-a"),
            ("momentum", "revision-1", "2026-09-10", "inst-b", "BBB", 0.6, 1.0, "score-b"),
            ("momentum", "revision-1", "2026-09-11", "inst-a", "AAA", 0.8, 1.0, "score-c"),
        ],
    )
    repository.upsert_daily_scores_for_date(
        "revision-1",
        "2026-09-10",
        [("momentum", "revision-1", "2026-09-10", "inst-a", "AAA", 0.9, 0.5, "score-d")],
        ("inst-a",),
    )
    rows = repository.daily_scores("revision-1", "2026-09-10", "2026-09-11")
    assert [(row["instrument_id"], row["score"]) for row in rows] == [
        ("inst-a", 0.9),
        ("inst-b", 0.6),
        ("inst-a", 0.8),
    ]


def test_weekly_rankings_replace_rows_and_list_ordered_weeks(tmp_path):
    repository = _research_repository(tmp_path)
    members = [
        {"instrument_id": "inst-a", "symbol": "AAA", "composite_score": 0.9, "rank": 1},
        {"instrument_id": "inst-b", "symbol": "BBB", "composite_score": 0.8, "rank": 2},
    ]
    repository.replace_weekly_rankings("momentum", "revision-1", "2026-09-11", "rank-a", members)
    assert repository.top_rankings("revision-1", "2026-09-11", 1)[0]["instrument_id"] == "inst-a"
    repository.replace_weekly_rankings(
        "momentum",
        "revision-1",
        "2026-09-11",
        "rank-b",
        [{"instrument_id": "inst-b", "symbol": "BBB", "composite_score": 0.95, "rank": 1}],
    )
    rows = repository.all_rankings("revision-1", "2026-09-11")
    assert [(row["instrument_id"], row["artifact_id"]) for row in rows] == [("inst-b", "rank-b")]
    assert repository.ranking_weeks("revision-1") == ("2026-09-11",)
