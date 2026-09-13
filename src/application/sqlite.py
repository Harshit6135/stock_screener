"""Atomic, namespaced schema migrations for the shared local SQLite store."""

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.platform_kernel import DomainValidationError


Migration = Sequence[str]


@contextmanager
def sqlite_connection(
    path: str | Path,
    *,
    read_only: bool = False,
    row_factory: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Open a consistently configured connection and always close its handle."""
    database = Path(path)
    if read_only:
        connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    else:
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
    try:
        if row_factory:
            connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        if not read_only:
            connection.execute("PRAGMA journal_mode=WAL")
        yield connection
        if not read_only:
            connection.commit()
    except Exception:
        if not read_only:
            connection.rollback()
        raise
    finally:
        connection.close()


def migrate_sqlite(path: str | Path, namespace: str, migrations: Mapping[int, Migration]) -> None:
    """Apply append-only migrations atomically, independently per namespace."""
    database = Path(path)
    versions = tuple(sorted(migrations))
    if not namespace or versions != tuple(range(1, len(versions) + 1)):
        raise DomainValidationError("SQLite migration versions must start at 1 and be contiguous")
    with sqlite_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS system_schema_migrations (namespace TEXT NOT NULL, version INTEGER NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(namespace, version))"
        )
        current = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM system_schema_migrations WHERE namespace = ?", (namespace,)
        ).fetchone()[0]
        if current > len(versions):
            raise DomainValidationError("SQLite database schema is newer than this application")
        for version in range(current + 1, len(versions) + 1):
            for statement in migrations[version]:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO system_schema_migrations(namespace, version) VALUES (?, ?)",
                (namespace, version),
            )
