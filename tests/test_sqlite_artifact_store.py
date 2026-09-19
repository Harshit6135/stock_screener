import sqlite3

import pytest

from src.application.catalog import ArtifactCatalog
from src.application.publication import ArtifactPublisher
from src.platform_kernel import (
    ArtifactStore,
    DomainValidationError,
    QualityStatus,
    SqliteArtifactStore,
)


def test_sqlite_artifact_store_keeps_payload_and_manifest_in_one_database(tmp_path):
    database = tmp_path / "system.db"
    store = SqliteArtifactStore(database)

    manifest = store.publish_json(
        "research/scores",
        "score-1",
        {"value": 42},
        upstream_ids=("source-1",),
        quality=QualityStatus.PARTIAL,
    )

    loaded_manifest, payload = store.read_json("research/scores", "score-1")
    assert loaded_manifest == manifest
    assert payload == {"value": 42}
    assert store.artifact_locations() == (("research/scores", "score-1"),)
    assert not (tmp_path / "artifacts").exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_payloads").fetchone()[0] == 1


def test_sqlite_artifact_store_rejects_duplicates_and_can_quarantine(tmp_path):
    store = SqliteArtifactStore(tmp_path / "system.db")
    store.publish_json("reference/test", "one", {"value": 1})

    with pytest.raises(DomainValidationError, match="already exists"):
        store.publish_json("reference/test", "one", {"value": 2})

    assert store.quarantine("reference/test", "one").startswith("one-")
    assert not store.is_published("reference/test", "one")


def test_sqlite_publisher_restores_catalog_entry_whose_legacy_payload_is_missing(tmp_path):
    database = tmp_path / "system.db"
    catalog = ArtifactCatalog(database)
    legacy = ArtifactStore(tmp_path / "legacy")
    manifest = legacy.publish_json("test", "one", {"old": True})
    catalog.register(manifest)
    catalog.mark_missing("one", "legacy file was not migrated")
    publisher = ArtifactPublisher(SqliteArtifactStore(database), catalog)

    restored = publisher.publish_json("test", "one", {"new": True})

    assert restored.artifact_id == "one"
    assert catalog.summaries(("one",))["one"]["status"] == "VALID"
    assert publisher.store.read_json("test", "one")[1] == {"new": True}
