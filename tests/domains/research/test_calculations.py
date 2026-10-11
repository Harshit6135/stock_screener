from src.domains.research import (
    correlation_clusters,
    detect_return_anomalies,
    rank_sector_factors,
    weekly_ranking_members,
)


def test_sector_factors_are_z_scored_and_ranked_by_weighted_score():
    members = rank_sector_factors(
        {
            "a": {"symbol": "AAA", "factors": {"trend": 1.0, "quality": 3.0}},
            "b": {"symbol": "BBB", "factors": {"trend": 2.0, "quality": 2.0}},
            "c": {"symbol": "CCC", "factors": {"trend": 3.0, "quality": 1.0}},
        },
        {"a": "TECH", "b": "TECH", "c": "TECH"},
        {"trend": 1.0, "quality": 0.0},
    )

    assert [member["instrument_id"] for member in members] == ["c", "b", "a"]
    assert [member["rank"] for member in members] == [1, 2, 3]
    assert members[0]["factor_zscores"]["trend"] > 0


def test_correlations_use_aligned_returns_and_absolute_threshold():
    closes = {
        "a": {str(day): value for day, value in enumerate((100, 101, 100, 103, 102))},
        "b": {str(day): value for day, value in enumerate((200, 202, 200, 206, 204))},
        "c": {str(day): value for day, value in enumerate((100, 101, 103, 100, 104))},
    }

    matrix, clusters = correlation_clusters(closes, 0.99)

    assert matrix["a"]["b"] > 0.99
    assert clusters == [["a", "b"], ["c"]]


def test_anomalies_report_latest_return_and_bar_lineage():
    bars = [
        {
            "as_of_date": f"2026-01-{day:02d}",
            "close": close,
            "snapshot_id": f"bar-{day}",
        }
        for day, close in enumerate((100, 101, 102, 103, 104, 130), start=1)
    ]

    rows, upstream_ids = detect_return_anomalies(
        {"instrument": (bars, {"isin": "INE000000001", "symbol": "ABC"})},
        lookback=20,
        threshold=2,
        minimum=3,
    )

    assert rows[0]["anomaly"] is True
    assert rows[0]["latest_date"] == "2026-01-06"
    assert upstream_ids == {f"bar-{day}" for day in range(1, 7)}


def test_weekly_rankings_preserve_symbol_ties_and_artifact_lineage():
    members, upstream_ids = weekly_ranking_members(
        [
            {"instrument_id": "b", "symbol": "BBB", "score": 50, "artifact_id": "s1"},
            {"instrument_id": "a", "symbol": "AAA", "score": 50, "artifact_id": "s2"},
            {"instrument_id": "a", "symbol": "AAA", "score": 70, "artifact_id": "s3"},
        ]
    )

    assert [member["instrument_id"] for member in members] == ["a", "b"]
    assert members[0]["composite_score"] == 60
    assert members[0]["sampled_sessions"] == 2
    assert upstream_ids == {"s1", "s2", "s3"}
