"""Recoverable composition of immutable files and catalog metadata."""

from typing import Any

from src.application.catalog import ArtifactCatalog
from src.platform_kernel import (
    ArtifactManifest,
    ArtifactStore,
    DomainValidationError,
    QualityStatus,
)


class ArtifactPublisher:
    def __init__(self, store: ArtifactStore, catalog: ArtifactCatalog):
        self.store = store
        self.catalog = catalog

    def publish_json(
        self,
        category: str,
        artifact_id: str,
        payload: dict[str, Any],
        *,
        upstream_ids: tuple[str, ...] = (),
        quality: QualityStatus = QualityStatus.COMPLETE,
        schema_version: str = "1",
    ) -> ArtifactManifest:
        restore_missing = self.catalog.is_missing(artifact_id) and not self.store.is_published(
            category, artifact_id
        )
        if self.catalog.has(artifact_id) and not restore_missing:
            raise DomainValidationError("artifact is already cataloged")
        self.catalog.set_publication_state(artifact_id, "STAGED")
        try:
            manifest = self.store.publish_json(
                category, artifact_id, payload, upstream_ids, quality, schema_version
            )
            self.catalog.set_publication_state(artifact_id, "FILES_PUBLISHED")
            self.catalog.register(manifest, replace_missing=restore_missing)
            return manifest
        except Exception as exc:
            self.catalog.set_publication_state(artifact_id, "FAILED", type(exc).__name__)
            raise

    def recover(self) -> dict[str, tuple[str, ...]]:
        """Reconcile stored payloads after a crash and flag missing catalog entries."""
        removed = self.store.recover_staging()
        registered: list[str] = []
        missing: list[str] = []
        quarantined: list[str] = []
        published_locations: set[tuple[str, str]] = set()
        for category, artifact_id in self.store.artifact_locations():
            try:
                manifest, _ = self.store.read_json(category, artifact_id)
            except DomainValidationError as exc:
                self.store.quarantine(category, artifact_id)
                self.catalog.set_publication_state(artifact_id, "QUARANTINED", type(exc).__name__)
                if self.catalog.has(artifact_id):
                    self.catalog.mark_missing(artifact_id, "artifact failed recovery validation")
                quarantined.append(artifact_id)
                continue
            published_locations.add((category, artifact_id))
            if not self.catalog.has(manifest.artifact_id):
                self.catalog.register(manifest)
                registered.append(manifest.artifact_id)
        for artifact in self.catalog.artifacts():
            if artifact["status"] != "MISSING" and (
                artifact["category"], artifact["artifact_id"]
            ) not in published_locations:
                self.catalog.mark_missing(
                    artifact["artifact_id"], "artifact payload is absent during recovery"
                )
                missing.append(artifact["artifact_id"])
        return {
            "staging_removed": removed,
            "catalog_registered": tuple(registered),
            "catalog_missing": tuple(missing),
            "quarantined": tuple(quarantined),
        }
