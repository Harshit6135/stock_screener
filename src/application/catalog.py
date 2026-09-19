"""SQLite catalog for immutable artifacts, lineage, and supersession."""

import json
import sqlite3
from pathlib import Path

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import ArtifactManifest, DomainValidationError


class ArtifactCatalog:
    def __init__(self, path: str | Path):
        self.path = str(path)
        migrate_sqlite(
            self.path,
            "catalog",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS catalog_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    checksum_sha256 TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'VALID'
                );""",
                    """CREATE TABLE IF NOT EXISTS catalog_lineage (
                    artifact_id TEXT NOT NULL,
                    upstream_id TEXT NOT NULL,
                    PRIMARY KEY(artifact_id, upstream_id),
                    FOREIGN KEY(artifact_id) REFERENCES catalog_artifacts(artifact_id)
                );""",
                ),
                2: (
                    "ALTER TABLE catalog_artifacts ADD COLUMN schema_version TEXT NOT NULL DEFAULT '1';",
                    "ALTER TABLE catalog_artifacts ADD COLUMN created_at TEXT NOT NULL DEFAULT '';",
                    "ALTER TABLE catalog_artifacts ADD COLUMN artifact_uri TEXT NOT NULL DEFAULT '';",
                    "ALTER TABLE catalog_artifacts ADD COLUMN manifest_json TEXT NOT NULL DEFAULT '{}';",
                    "ALTER TABLE catalog_artifacts ADD COLUMN status_reason TEXT;",
                    "CREATE TABLE IF NOT EXISTS catalog_publications (artifact_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, error TEXT)",
                ),
                3: (
                    "CREATE INDEX IF NOT EXISTS catalog_artifacts_status_index ON catalog_artifacts(status)",
                    "CREATE INDEX IF NOT EXISTS catalog_lineage_upstream_index ON catalog_lineage(upstream_id)",
                    """CREATE TABLE IF NOT EXISTS catalog_invalidations (
                    source_artifact_id TEXT NOT NULL,
                    affected_artifact_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(source_artifact_id, affected_artifact_id)
                )""",
                    """CREATE TABLE IF NOT EXISTS catalog_tombstones (
                    artifact_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
                ),
            },
        )

    def _connect(self):
        return sqlite_connection(self.path, row_factory=True)

    def register(self, manifest: ArtifactManifest, *, replace_missing: bool = False) -> None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT status FROM catalog_artifacts WHERE artifact_id = ?",
                (manifest.artifact_id,),
            ).fetchone()
            try:
                values = (
                    manifest.category,
                    manifest.checksum_sha256,
                    manifest.quality.value,
                    manifest.schema_version,
                    manifest.created_at,
                    f"{manifest.category}/{manifest.artifact_id}",
                    json.dumps(
                        {
                            "artifact_id": manifest.artifact_id,
                            "category": manifest.category,
                            "schema_version": manifest.schema_version,
                            "created_at": manifest.created_at,
                            "checksum_sha256": manifest.checksum_sha256,
                            "upstream_ids": manifest.upstream_ids,
                            "quality": manifest.quality.value,
                        },
                        sort_keys=True,
                    ),
                )
                if existing is None:
                    connection.execute(
                        "INSERT INTO catalog_artifacts(artifact_id, category, checksum_sha256, quality, schema_version, created_at, artifact_uri, manifest_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (manifest.artifact_id, *values),
                    )
                elif replace_missing and existing["status"] == "MISSING":
                    connection.execute(
                        """UPDATE catalog_artifacts SET category=?, checksum_sha256=?, quality=?,
                           schema_version=?, created_at=?, artifact_uri=?, manifest_json=?,
                           status='VALID', status_reason=NULL WHERE artifact_id=?""",
                        (*values, manifest.artifact_id),
                    )
                    connection.execute(
                        "DELETE FROM catalog_lineage WHERE artifact_id=?", (manifest.artifact_id,)
                    )
                else:
                    raise DomainValidationError("artifact is already cataloged")
            except sqlite3.IntegrityError as exc:
                raise DomainValidationError("artifact is already cataloged") from exc
            connection.executemany(
                "INSERT INTO catalog_lineage(artifact_id, upstream_id) VALUES (?, ?)",
                [(manifest.artifact_id, upstream_id) for upstream_id in manifest.upstream_ids],
            )
            connection.execute(
                "INSERT OR REPLACE INTO catalog_publications(artifact_id, state) VALUES (?, 'CATALOGED')",
                (manifest.artifact_id,),
            )

    def set_publication_state(self, artifact_id: str, state: str, error: str | None = None) -> None:
        if state not in {"STAGED", "FILES_PUBLISHED", "CATALOGED", "FAILED", "QUARANTINED"}:
            raise DomainValidationError("publication state is invalid")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO catalog_publications(artifact_id, state, updated_at, error)
                   VALUES (?, ?, CURRENT_TIMESTAMP, ?)
                   ON CONFLICT(artifact_id) DO UPDATE SET
                     state = excluded.state,
                     updated_at = CURRENT_TIMESTAMP,
                     error = excluded.error""",
                (artifact_id, state, error),
            )

    def has(self, artifact_id: str) -> bool:
        with self._connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM catalog_artifacts WHERE artifact_id = ?", (artifact_id,)
                ).fetchone()
                is not None
            )

    def is_missing(self, artifact_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM catalog_artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        return row is not None and row["status"] == "MISSING"

    def summaries(self, artifact_ids: tuple[str, ...]) -> dict[str, dict[str, str]]:
        """Read quality and validity for a bounded set of source artifacts."""
        identifiers = tuple(dict.fromkeys(artifact_ids))
        if len(identifiers) > 500:
            raise DomainValidationError("artifact summary batch is too large")
        if not identifiers:
            return {}
        with self._connect() as connection:
            rows = [
                row
                for artifact_id in identifiers
                if (
                    row := connection.execute(
                        "SELECT artifact_id, quality, status FROM catalog_artifacts "
                        "WHERE artifact_id = ?",
                        (artifact_id,),
                    ).fetchone()
                )
                is not None
            ]
        return {
            str(row["artifact_id"]): {
                "quality": str(row["quality"]),
                "status": str(row["status"]),
            }
            for row in rows
        }

    def mark_missing(self, artifact_id: str, reason: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE catalog_artifacts SET status = 'MISSING', status_reason = ? WHERE artifact_id = ?",
                (reason, artifact_id),
            )

    def set_status(self, artifact_id: str, status: str, reason: str) -> None:
        if status not in {"VALID", "SUPERSEDED", "QUALIFIED", "REVOKED", "MISSING"}:
            raise DomainValidationError("artifact status is invalid")
        if not reason:
            raise DomainValidationError("artifact status change requires a reason")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE catalog_artifacts SET status = ?, status_reason = ? WHERE artifact_id = ?",
                (status, reason, artifact_id),
            )
            if cursor.rowcount != 1:
                raise DomainValidationError("artifact is not cataloged")

    def artifacts(self) -> tuple[dict[str, str], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT artifact_id, category, status FROM catalog_artifacts ORDER BY artifact_id"
            ).fetchall()
        return tuple(
            {
                "artifact_id": row["artifact_id"],
                "category": row["category"],
                "status": row["status"],
            }
            for row in rows
        )

    def supersede(self, previous_id: str, replacement_id: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT status FROM catalog_artifacts WHERE artifact_id = ?", (previous_id,)
            ).fetchone()
            replacement = connection.execute(
                "SELECT status FROM catalog_artifacts WHERE artifact_id = ?", (replacement_id,)
            ).fetchone()
            if previous is None or replacement is None:
                raise DomainValidationError("both artifacts must be cataloged before supersession")
            if replacement["status"] != "VALID":
                raise DomainValidationError("replacement artifact is not valid")
            # The replacement and its descendants are the new valid branch.
            # Collect the previous branch before linking its replacement;
            # otherwise the new branch appears to descend from the old one.
            affected_ids = set(self._invalidation_plan(connection, previous_id))
            replacement_branch = set(self._invalidation_plan(connection, replacement_id))
            affected_ids.difference_update(replacement_branch)
            affected_ids.discard(replacement_id)
            connection.execute(
                "UPDATE catalog_artifacts SET status = 'SUPERSEDED' WHERE artifact_id = ?",
                (previous_id,),
            )
            connection.execute(
                "INSERT OR IGNORE INTO catalog_lineage(artifact_id, upstream_id) VALUES (?, ?)",
                (replacement_id, previous_id),
            )
            for affected_id in sorted(affected_ids):
                connection.execute(
                    "UPDATE catalog_artifacts SET status = 'QUALIFIED', status_reason = ? WHERE artifact_id = ? AND status = 'VALID'",
                    (f"upstream artifact {previous_id} was superseded", affected_id),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO catalog_invalidations(source_artifact_id, affected_artifact_id, reason) VALUES (?, ?, ?)",
                    (previous_id, affected_id, "upstream superseded"),
                )

    def invalidation_plan(self, artifact_id: str) -> tuple[str, ...]:
        """Return all direct and transitive descendants requiring qualification."""
        with self._connect() as connection:
            return self._invalidation_plan(connection, artifact_id)

    def record_invalidation(self, source_artifact_id: str, affected_artifact_id: str, reason: str) -> None:
        if not reason:
            raise DomainValidationError("invalidation reason is required")
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO catalog_invalidations(source_artifact_id, affected_artifact_id, reason) VALUES (?, ?, ?)",
                (source_artifact_id, affected_artifact_id, reason),
            )

    @staticmethod
    def _invalidation_plan(connection: sqlite3.Connection, artifact_id: str) -> tuple[str, ...]:
        rows = connection.execute(
            """
                WITH RECURSIVE descendants(id) AS (
                    SELECT artifact_id FROM catalog_lineage WHERE upstream_id = ?
                    UNION
                    SELECT catalog_lineage.artifact_id FROM catalog_lineage
                    JOIN descendants ON catalog_lineage.upstream_id = descendants.id
                ) SELECT id FROM descendants ORDER BY id
                """,
            (artifact_id,),
        ).fetchall()
        return tuple(row["id"] for row in rows)
