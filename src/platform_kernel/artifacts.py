"""Crash-safe, immutable JSON artifact publishing for research snapshots."""

import hashlib
import json
import os
import sqlite3
import shutil
import zlib
from contextlib import closing
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


class SqliteArtifactStore(ArtifactStore):
    """Immutable compressed JSON artifacts stored inside the application database."""

    def __init__(self, database: str | Path):
        self.database = Path(database)
        self.root = self.database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS artifact_payloads (
                    artifact_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    checksum_sha256 TEXT NOT NULL,
                    upstream_ids_json TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    payload_zlib BLOB NOT NULL,
                    quarantined INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(category, artifact_id)
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS artifact_payloads_category ON artifact_payloads(category, quarantined)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def publish_json(
        self,
        category: str,
        artifact_id: str,
        payload: dict[str, Any],
        upstream_ids: tuple[str, ...] = (),
        quality: QualityStatus = QualityStatus.COMPLETE,
        schema_version: str = "1",
    ) -> ArtifactManifest:
        self._parts(category, "category")
        self._parts(artifact_id, "artifact_id")
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
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """INSERT INTO artifact_payloads
                       (artifact_id, category, schema_version, created_at, checksum_sha256,
                        upstream_ids_json, quality, payload_zlib)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        artifact_id,
                        category,
                        schema_version,
                        manifest.created_at,
                        manifest.checksum_sha256,
                        json.dumps(upstream_ids),
                        quality.value,
                        zlib.compress(payload_bytes),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DomainValidationError(f"artifact already exists: {category}/{artifact_id}") from exc
        return manifest

    def read_json(self, category: str, artifact_id: str) -> tuple[ArtifactManifest, dict[str, Any]]:
        self._parts(category, "category")
        self._parts(artifact_id, "artifact_id")
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT * FROM artifact_payloads
                   WHERE category=? AND artifact_id=? AND quarantined=0""",
                (category, artifact_id),
            ).fetchone()
        if row is None:
            raise DomainValidationError("artifact is missing or malformed")
        try:
            payload = json.loads(zlib.decompress(row["payload_zlib"]).decode("utf-8"))
            upstream_ids = tuple(json.loads(row["upstream_ids_json"]))
            quality = QualityStatus(row["quality"])
        except (TypeError, ValueError, json.JSONDecodeError, zlib.error) as exc:
            raise DomainValidationError("artifact is missing or malformed") from exc
        if not isinstance(payload, dict):
            raise DomainValidationError("artifact payload must contain a JSON object")
        checksum = hashlib.sha256(self._encode(payload)).hexdigest()
        if checksum != row["checksum_sha256"]:
            raise DomainValidationError("artifact checksum does not match manifest")
        return (
            ArtifactManifest(
                artifact_id=row["artifact_id"],
                category=row["category"],
                schema_version=row["schema_version"],
                created_at=row["created_at"],
                checksum_sha256=row["checksum_sha256"],
                upstream_ids=upstream_ids,
                quality=quality,
            ),
            payload,
        )

    def recover_staging(self) -> tuple[str, ...]:
        return ()

    def manifests(self) -> tuple[ArtifactManifest, ...]:
        return tuple(self.read_json(category, artifact_id)[0] for category, artifact_id in self.artifact_locations())

    def artifact_locations(self) -> tuple[tuple[str, str], ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT category, artifact_id FROM artifact_payloads WHERE quarantined=0 ORDER BY category, artifact_id"
            ).fetchall()
        return tuple((str(row["category"]), str(row["artifact_id"])) for row in rows)

    def quarantine(self, category: str, artifact_id: str) -> str:
        name = f"{artifact_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE artifact_payloads SET quarantined=1 WHERE category=? AND artifact_id=?",
                (category, artifact_id),
            )
        if cursor.rowcount != 1:
            raise DomainValidationError("artifact is missing or malformed")
        return name

    def is_published(self, category: str, artifact_id: str) -> bool:
        try:
            self.read_json(category, artifact_id)
        except DomainValidationError:
            return False
        return True
