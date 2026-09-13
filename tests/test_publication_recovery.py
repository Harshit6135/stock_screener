from src.application import ArtifactCatalog, ArtifactPublisher
from src.platform_kernel import ArtifactStore


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
