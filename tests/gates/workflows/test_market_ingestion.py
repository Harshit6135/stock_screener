from datetime import date
from decimal import Decimal

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.market_data import NormalizedBar
from src.gates.workflows.market_ingestion import ingest_market_bars
from src.platform_kernel import ArtifactStore


def test_ingestion_publishes_redacted_raw_and_normalized_lineage(tmp_path):
    publisher = ArtifactPublisher(
        ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(tmp_path / "system.db")
    )
    bar = NormalizedBar(
        "ABC", date(2026, 1, 2), Decimal(10), Decimal(12), Decimal(9), Decimal(11), 5
    )
    raw, normalized = ingest_market_bars(publisher, "fake", [bar], source_request={"query": "ABC"})
    assert normalized.upstream_ids == (raw.artifact_id,)


def test_ingestion_redacts_nested_secrets_and_preserves_raw_response(tmp_path):
    publisher = ArtifactPublisher(
        ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(tmp_path / "system.db")
    )
    bar = NormalizedBar("ABC", date(2026, 1, 2), 10, 12, 9, 11, 5)
    raw, _ = ingest_market_bars(
        publisher,
        "fake",
        (bar,),
        source_request={"api_key": "LEAK", "nested": {"token": "LEAK"}},
        raw_payload={"records": [{"symbol": "ABC", "close": 11}]},
        provider_version="1",
    )
    _, payload = publisher.store.read_json(raw.category, raw.artifact_id)

    assert payload["request"]["api_key"] == "[REDACTED]"
    assert payload["request"]["nested"]["token"] == "[REDACTED]"
    assert payload["response"]["records"][0]["close"] == 11
    assert payload["capture"] == "provider_raw"
