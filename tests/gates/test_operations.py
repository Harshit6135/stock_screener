import sqlite3
from contextlib import closing

import pytest

from src.gates.operations import sqlite_backup, sqlite_ready, sqlite_restore, sqlite_vacuum
from src.platform_kernel import DomainValidationError


def test_sqlite_backup_is_consistent_and_readiness_checks_database(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "backup.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE values_table (value INTEGER)")
        connection.execute("INSERT INTO values_table VALUES (7)")
        connection.commit()

    assert sqlite_ready(source)
    assert sqlite_backup(source, destination) == destination
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("SELECT value FROM values_table").fetchone()[0] == 7
    restored = tmp_path / "restored.db"
    assert sqlite_restore(destination, restored) == restored
    assert sqlite_ready(restored)


def test_missing_database_is_not_ready_or_created(tmp_path):
    missing = tmp_path / "missing.db"

    assert not sqlite_ready(missing)
    assert not missing.exists()


def test_sqlite_vacuum_reclaims_pages_and_validates_path(tmp_path):
    database = tmp_path / "vacuum_test.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE t (x TEXT)")
        connection.execute("INSERT INTO t VALUES ('sample data')")
        connection.commit()

    sqlite_vacuum(database)
    assert sqlite_ready(database)

    with pytest.raises(DomainValidationError, match="does not exist"):
        sqlite_vacuum(tmp_path / "nonexistent.db")

