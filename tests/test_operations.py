import sqlite3

from src.application import sqlite_backup, sqlite_ready, sqlite_restore


def test_sqlite_backup_is_consistent_and_readiness_checks_database(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "backup.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE values_table (value INTEGER)")
        connection.execute("INSERT INTO values_table VALUES (7)")

    assert sqlite_ready(source)
    assert sqlite_backup(source, destination) == destination
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM values_table").fetchone()[0] == 7
    restored = tmp_path / "restored.db"
    assert sqlite_restore(destination, restored) == restored
    assert sqlite_ready(restored)
