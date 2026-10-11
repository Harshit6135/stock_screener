from src.domains.artifacts import ArtifactCatalog
from src.platform_kernel.artifacts import ArtifactStore


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
    assert catalog.invalidation_plan("old-source") == ("new-score", "new-source", "old-score")
