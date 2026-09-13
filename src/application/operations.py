"""Local operational helpers: readiness checks and SQLite-safe backups."""

import sqlite3
from contextlib import closing
from pathlib import Path

from src.platform_kernel import DomainValidationError


def sqlite_backup(source: str | Path, destination: str | Path) -> Path:
    """Create a consistent SQLite backup using SQLite's online backup API."""
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise DomainValidationError("SQLite source database does not exist")
    if destination.exists():
        raise DomainValidationError("SQLite backup destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)) as source_connection:
        if source_connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise DomainValidationError("SQLite source database failed integrity check")
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)
            if destination_connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DomainValidationError("SQLite backup failed integrity check")
    return destination


def sqlite_restore(backup: str | Path, destination: str | Path) -> Path:
    """Restore only to a new destination so the source backup is preserved."""
    backup, destination = Path(backup), Path(destination)
    if not backup.is_file():
        raise DomainValidationError("SQLite backup does not exist")
    if destination.exists():
        raise DomainValidationError("restore destination already exists")
    return sqlite_backup(backup, destination)


def sqlite_ready(path: str | Path, required_namespaces: tuple[str, ...] = ()) -> bool:
    """Return whether a SQLite database can execute a read-only health query."""
    try:
        database = Path(path)
        if not database.is_file():
            return False
        with closing(
            sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
        ) as connection:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                return False
            if required_namespaces:
                rows = connection.execute(
                    "SELECT DISTINCT namespace FROM system_schema_migrations"
                ).fetchall()
                if not set(required_namespaces).issubset({row[0] for row in rows}):
                    return False
        return True
    except sqlite3.Error:
        return False
