"""Crash-safe, immutable JSON artifact publishing for research snapshots."""

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

from .errors import DomainValidationError


class QualityStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    MISSING = "MISSING"
    ADJUSTMENT_PENDING = "ADJUSTMENT_PENDING"
    SOURCE_FAILED = "SOURCE_FAILED"


@dataclass(frozen=True)
class ArtifactManifest:
    artifact_id: str
    category: str
    schema_version: str
    created_at: str
    checksum_sha256: str
    upstream_ids: tuple[str, ...]
    quality: QualityStatus


class ArtifactStore:
    """Publish complete artifacts atomically; never overwrite an existing ID."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".staging").mkdir(exist_ok=True)

    @staticmethod
    def _parts(value: str, field_name: str) -> tuple[str, ...]:
        path = Path(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise DomainValidationError(f"{field_name} must be a relative safe path")
        return path.parts

    @staticmethod
    def _encode(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    def publish_json(
        self,
        category: str,
        artifact_id: str,
        payload: dict[str, Any],
        upstream_ids: tuple[str, ...] = (),
        quality: QualityStatus = QualityStatus.COMPLETE,
        schema_version: str = "1",
    ) -> ArtifactManifest:
        category_parts = self._parts(category, "category")
        self._parts(artifact_id, "artifact_id")
        destination = self.root.joinpath(*category_parts, artifact_id)
        if destination.exists():
            raise DomainValidationError(f"artifact already exists: {category}/{artifact_id}")

        payload_bytes = self._encode(payload)
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            category=category,
            schema_version=schema_version,
            created_at=datetime.now(UTC).isoformat(),
            checksum_sha256=hashlib.sha256(payload_bytes).hexdigest(),
            upstream_ids=tuple(upstream_ids),
            quality=quality,
        )
        staging = Path(mkdtemp(prefix="artifact-", dir=self.root / ".staging"))
        try:
            payload_path = staging / "payload.json"
            manifest_path = staging / "manifest.json"
            payload_path.write_bytes(payload_bytes)
            manifest_path.write_text(
                json.dumps(asdict(manifest), default=str, sort_keys=True), encoding="utf-8"
            )
            # Windows requires a writable handle for fsync.
            with payload_path.open("r+b") as handle:
                os.fsync(handle.fileno())
            with manifest_path.open("r+b") as handle:
                os.fsync(handle.fileno())
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
            return manifest
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def read_json(self, category: str, artifact_id: str) -> tuple[ArtifactManifest, dict[str, Any]]:
        directory = self.root.joinpath(
            *self._parts(category, "category"), *self._parts(artifact_id, "artifact_id")
        )
        try:
            manifest_data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            payload = json.loads((directory / "payload.json").read_text(encoding="utf-8"))
            if not isinstance(manifest_data, dict) or not isinstance(payload, dict):
                raise DomainValidationError("artifact files must contain JSON objects")
            if (
                manifest_data.get("artifact_id") != artifact_id
                or manifest_data.get("category") != category
            ):
                raise DomainValidationError("artifact manifest identity does not match its path")
            required = {
                "schema_version",
                "created_at",
                "checksum_sha256",
                "upstream_ids",
                "quality",
            }
            if not required.issubset(manifest_data):
                raise DomainValidationError("artifact manifest is incomplete")
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise DomainValidationError("artifact is missing or malformed") from exc
        checksum = hashlib.sha256(self._encode(payload)).hexdigest()
        if checksum != manifest_data["checksum_sha256"]:
            raise DomainValidationError("artifact checksum does not match manifest")
        try:
            manifest_data["upstream_ids"] = tuple(manifest_data["upstream_ids"])
            manifest_data["quality"] = QualityStatus(manifest_data["quality"])
            return ArtifactManifest(**manifest_data), payload
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("artifact manifest fields are invalid") from exc

    def recover_staging(self) -> tuple[str, ...]:
        """Remove abandoned private staging directories; published paths are untouched."""
        removed: list[str] = []
        for candidate in (self.root / ".staging").iterdir():
            if candidate.is_dir() and candidate.name.startswith("artifact-"):
                shutil.rmtree(candidate)
                removed.append(candidate.name)
        return tuple(removed)

    def manifests(self) -> tuple[ArtifactManifest, ...]:
        """Return every checksum-verified published manifest."""
        results: list[ArtifactManifest] = []
        for category, artifact_id in self.artifact_locations():
            manifest, _ = self.read_json(category, artifact_id)
            results.append(manifest)
        return tuple(results)

    def artifact_locations(self) -> tuple[tuple[str, str], ...]:
        """Return candidate artifact locations without trusting their manifests."""
        locations: list[tuple[str, str]] = []
        for manifest_path in self.root.rglob("manifest.json"):
            relative = manifest_path.parent.relative_to(self.root)
            if not relative.parts or relative.parts[0] in {".staging", ".quarantine"}:
                continue
            locations.append(("/".join(relative.parts[:-1]), relative.parts[-1]))
        return tuple(sorted(locations))

    def quarantine(self, category: str, artifact_id: str) -> str:
        """Move invalid published files to a recoverable private namespace."""
        source = self.root.joinpath(
            *self._parts(category, "category"), *self._parts(artifact_id, "artifact_id")
        )
        quarantine_root = self.root / ".quarantine"
        quarantine_root.mkdir(exist_ok=True)
        destination = (
            quarantine_root / f"{artifact_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
        )
        os.replace(source, destination)
        return destination.name

    def is_published(self, category: str, artifact_id: str) -> bool:
        try:
            self.read_json(category, artifact_id)
        except DomainValidationError:
            return False
        return True
