import sqlite3
from contextlib import closing

import pytest

from src.application.sqlite import migrate_sqlite
from src.platform_kernel import DomainValidationError


def test_private_store_migrations_are_versioned_and_idempotent(tmp_path):
    database = tmp_path / "nested" / "state.db"
    migrations = {
        1: ("CREATE TABLE values_table (value TEXT NOT NULL);",),
        2: ("CREATE INDEX values_index ON values_table(value);",),
    }
    migrate_sqlite(database, "test", migrations)
    migrate_sqlite(database, "test", migrations)
    with closing(sqlite3.connect(database)) as connection:
        assert (
            connection.execute(
                "SELECT MAX(version) FROM system_schema_migrations WHERE namespace = 'test'"
            ).fetchone()[0]
            == 2
        )
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'values_index'"
        ).fetchone()
    with pytest.raises(DomainValidationError, match="contiguous"):
        migrate_sqlite(tmp_path / "invalid.db", "test", {2: ("SELECT 1;",)})


def test_failed_migration_is_atomic_and_does_not_advance_version(tmp_path):
    database = tmp_path / "atomic.db"
    with pytest.raises(sqlite3.OperationalError):
        migrate_sqlite(
            database,
            "atomic",
            {
                1: (
                    "CREATE TABLE valid_table (value INTEGER)",
                    "CREATE TABLE valid_table (value INTEGER)",
                )
            },
        )
    with closing(sqlite3.connect(database)) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'valid_table'"
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'system_schema_migrations'"
            ).fetchone()
            is None
        )
