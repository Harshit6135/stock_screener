from datetime import date
from decimal import Decimal

from src.application import ArtifactCatalog, ArtifactPublisher
from src.application.ingestion import ingest_market_bars
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore


def test_ingestion_publishes_redacted_raw_and_normalized_lineage(tmp_path):
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(tmp_path / "system.db"))
    bar = NormalizedBar("ABC", date(2026, 1, 2), Decimal("10"), Decimal("12"), Decimal("9"), Decimal("11"), 5)
    raw, normalized = ingest_market_bars(publisher, "fake", [bar], source_request={"query": "ABC"})
    assert normalized.upstream_ids == (raw.artifact_id,)
