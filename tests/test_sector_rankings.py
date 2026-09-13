from datetime import date, timedelta
from decimal import Decimal

from src.application.catalog import ArtifactCatalog
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore


def test_sector_normalized_ranking_is_versioned_and_lineaged(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    features = publisher.publish_json(
        "features/strategy1", "features-1", {
            "snapshot_id": "features-1", "as_of_date": "2026-09-10", "strategy_id": "strategy1",
            "values": {
                "a": {"symbol": "AAA", "factors": {"trend": 1, "momentum": 1, "efficiency": 1, "volume": 1, "structure": 1}},
                "b": {"symbol": "BBB", "factors": {"trend": 2, "momentum": 2, "efficiency": 2, "volume": 2, "structure": 2}},
            },
        }
    )
    sectors = publisher.publish_json("reference/sectors", "sectors-1", {"snapshot_id": "sectors-1", "as_of_date": "2026-09-10", "values": {"a": "TECH", "b": "TECH"}})
    research = ResearchJobs(database, MarketRepository(database), publisher)
    result = research.sector_normalize({"as_of_date": "2026-09-10", "strategy_id": "strategy1", "feature_artifact_id": features.artifact_id, "sector_artifact_id": sectors.artifact_id})
    assert result["normalization"] == "within_sector_zscore"
    assert result["members"][0]["instrument_id"] == "b"
    manifest, _ = publisher.store.read_json("research/sector-rankings", result["artifact_id"])
    assert set(manifest.upstream_ids) == {"features-1", "sectors-1"}


def test_correlation_readback_clusters_point_in_time_returns(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    start = date(2026, 1, 1)
    market.upsert_instruments([
        TrackedInstrument("a", "IN000000010", "AAA", "NSE", "10", start),
        TrackedInstrument("b", "IN000000011", "BBB", "NSE", "11", start),
    ])
    for offset in range(25):
        day = start + timedelta(days=offset)
        market.upsert_bars("a", [NormalizedBar("a", day, Decimal(100 + offset), Decimal(101 + offset), Decimal(99 + offset), Decimal(100 + offset), 100)], f"a-{offset}")
        market.upsert_bars("b", [NormalizedBar("b", day, Decimal(200 + offset * 2), Decimal(202 + offset * 2), Decimal(198 + offset * 2), Decimal(200 + offset * 2), 100)], f"b-{offset}")
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    result = ResearchJobs(database, market, publisher).correlations({"as_of_date": "2026-01-25", "lookback_sessions": 20, "correlation_threshold": 0.9})
    assert result["clusters"] == [["a", "b"]]
    assert result["matrix"]["a"]["b"] > 0.9
