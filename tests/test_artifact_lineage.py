from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.application import ArtifactCatalog
from src.market_data import NormalizedBar, publish_snapshot
from src.platform_kernel import DomainValidationError
from src.platform_kernel.artifacts import ArtifactStore, QualityStatus
from src.reference_data import Instrument, publish_instrument_snapshot


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
                "ABC",
                date(2026, 1, 2),
                Decimal(100),
                Decimal(105),
                Decimal(99),
                Decimal(104),
                1000,
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


def test_catalog_tracks_supersession_and_transitive_invalidation(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    catalog = ArtifactCatalog(tmp_path / "catalog.db")
    source = store.publish_json("market/normalized/kite", "source", {"value": 1})
    dependent = store.publish_json(
        "research/scores", "dependent", {"value": 2}, upstream_ids=(source.artifact_id,)
    )
    replacement = store.publish_json("market/normalized/kite", "replacement", {"value": 3})
    for manifest in (source, dependent, replacement):
        catalog.register(manifest)

    catalog.supersede(source.artifact_id, replacement.artifact_id)

    assert catalog.invalidation_plan(source.artifact_id) == ("dependent", "replacement")


def test_supersession_keeps_replacement_descendants_valid(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    catalog = ArtifactCatalog(tmp_path / "catalog.db")
    old_source = store.publish_json("research/features", "old-source", {})
    old_score = store.publish_json(
        "research/scores", "old-score", {}, upstream_ids=(old_source.artifact_id,)
    )
    new_source = store.publish_json("research/features", "new-source", {})
    new_score = store.publish_json(
        "research/scores", "new-score", {}, upstream_ids=(new_source.artifact_id,)
    )
    for manifest in (old_source, old_score, new_source, new_score):
        catalog.register(manifest)

    catalog.supersede(old_source.artifact_id, new_source.artifact_id)

    statuses = {item["artifact_id"]: item["status"] for item in catalog.artifacts()}
    assert statuses == {
        "old-source": "SUPERSEDED",
        "old-score": "QUALIFIED",
        "new-source": "VALID",
        "new-score": "VALID",
    }
    assert catalog.invalidation_plan("old-source") == (
        "new-score",
        "new-source",
        "old-score",
    )
