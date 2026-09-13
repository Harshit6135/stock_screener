import sqlite3
import sys
from contextlib import closing

import pytest

from src.application import sqlite_backup, sqlite_ready, sqlite_restore
from src.application.cli import main
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


def test_operations_cli_backup_restore_readiness_and_idle_worker(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE values_table (value INTEGER)")
        connection.commit()

    monkeypatch.setattr(sys, "argv", ["screener-ops", "backup-sqlite", str(source), str(backup)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["screener-ops", "restore-sqlite", str(backup), str(restored)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["screener-ops", "check-sqlite", str(restored)])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["screener-ops", "work-once", str(tmp_path / "app")])
    assert main() == 0
    assert "idle" in capsys.readouterr().out

    with pytest.raises(DomainValidationError, match="already exists"):
        sqlite_backup(source, backup)
    with pytest.raises(DomainValidationError, match="does not exist"):
        sqlite_restore(tmp_path / "missing.db", tmp_path / "unused.db")
