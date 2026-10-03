from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.market_data import NormalizedBar, publish_snapshot
from src.domains.reference_data import Instrument, publish_instrument_snapshot
from src.platform_kernel import DomainValidationError, SqliteArtifactStore
from src.platform_kernel.artifacts import ArtifactStore, QualityStatus


def test_reference_and_market_artifacts_are_immutable_and_verifiable(tmp_path):
    store = ArtifactStore(tmp_path)
    instrument_manifest = publish_instrument_snapshot(
        store, [Instrument(uuid4(), "INE000000001", "ABC", "NSE")]
    )
    market_manifest = publish_snapshot(
        store,
        "kite",
        [
            NormalizedBar(
                "ABC", date(2026, 1, 2), Decimal(100), Decimal(105), Decimal(99), Decimal(104), 1000
            )
        ],
        upstream_ids=(instrument_manifest.artifact_id,),
        quality=QualityStatus.COMPLETE,
    )
    manifest, payload = store.read_json(market_manifest.category, market_manifest.artifact_id)
    assert manifest.upstream_ids == (instrument_manifest.artifact_id,)
    assert payload["bars"][0]["instrument_id"] == "ABC"
    with pytest.raises(DomainValidationError, match="already exists"):
        store.publish_json(market_manifest.category, market_manifest.artifact_id, payload)


def test_publication_recovery_registers_completed_uncataloged_artifact_and_cleans_staging(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    catalog = ArtifactCatalog(tmp_path / "system.db")
    manifest = store.publish_json("research/test", "one", {"value": 1})
    staging = store.root / ".staging" / "artifact-abandoned"
    staging.mkdir()
    result = ArtifactPublisher(store, catalog).recover()
    assert manifest.artifact_id in result["catalog_registered"]
    assert result["staging_removed"] == ("artifact-abandoned",)
    assert result["catalog_missing"] == ()


def test_recovery_quarantines_checksum_mismatch(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    catalog = ArtifactCatalog(tmp_path / "system.db")
    store.publish_json("research/test", "broken", {"value": 1})
    (store.root / "research" / "test" / "broken" / "payload.json").write_text(
        '{"value":2}', encoding="utf-8"
    )

    result = ArtifactPublisher(store, catalog).recover()

    assert result["quarantined"] == ("broken",)
    assert not catalog.has("broken")
    assert not store.is_published("research/test", "broken")


def test_sqlite_publisher_republishes_missing_catalog_artifact(tmp_path):
    database = tmp_path / "system.db"
    catalog = ArtifactCatalog(database)
    source_store = ArtifactStore(tmp_path / "source")
    manifest = source_store.publish_json("test", "one", {"previous": True})
    catalog.register(manifest)
    catalog.mark_missing("one", "payload is missing from the current store")
    publisher = ArtifactPublisher(SqliteArtifactStore(database), catalog)

    restored = publisher.publish_json("test", "one", {"new": True})

    assert restored.artifact_id == "one"
    assert catalog.summaries(("one",))["one"]["status"] == "VALID"
    assert publisher.store.read_json("test", "one")[1] == {"new": True}
