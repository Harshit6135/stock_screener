"""Tests for the operational CLI gate."""

import json
import sqlite3
import sys
from contextlib import closing

import pytest

from src.gates.cli import main
from src.gates.operations import sqlite_backup, sqlite_restore
from src.platform_kernel import DomainValidationError


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


def test_operations_cli_reads_pipeline_and_poller_state(tmp_path, monkeypatch, capsys):
    from src.domains.operations import JobStore
    from src.gates.workflows.index_poller import IndexQuotePoller
    from src.gates.workflows.research_pipeline import ResearchPipelineJobs

    database = tmp_path / "state.db"
    jobs = JobStore(database)
    pipeline = ResearchPipelineJobs(database, jobs).submit(
        {"as_of_date": "2026-09-10", "strategies": ["momentum"]}
    )
    monkeypatch.setattr(
        sys, "argv", ["screener-ops", "pipeline-status", str(database), pipeline["pipeline_id"]]
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["pipeline_id"] == pipeline["pipeline_id"]

    IndexQuotePoller(database, jobs)
    monkeypatch.setattr(sys, "argv", ["screener-ops", "poller-state", str(database)])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["enabled"] == 0

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "screener-ops",
            "stream-state",
            str(database),
            "--start-account",
            "paper",
            "--token-count",
            "2",
        ],
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "REQUESTED"
    monkeypatch.setattr(sys, "argv", ["screener-ops", "stream-state", str(database)])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["account_id"] == "paper"
