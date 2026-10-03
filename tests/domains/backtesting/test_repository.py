import sqlite3

import pytest

from src.domains.backtesting import BacktestRunStore
from src.platform_kernel import DomainValidationError


def _record(store: BacktestRunStore, run_id: str, created_at: str) -> None:
    store.record_run(
        run_id=run_id,
        artifact_id=f"artifact-{run_id}",
        strategy_id="momentum",
        start_date="2026-01-01",
        end_date="2026-01-31",
        fingerprint=f"fingerprint-{run_id}",
        total_return="0.12",
        max_drawdown="-0.08",
        created_at=created_at,
    )


def test_backtest_run_store_lists_reads_and_deletes_index_rows(tmp_path):
    store = BacktestRunStore(tmp_path / "system.db")
    _record(store, "run-1", "2026-02-01T00:00:00+00:00")
    _record(store, "run-2", "2026-02-02T00:00:00+00:00")

    assert [row["run_id"] for row in store.list_runs()] == ["run-2", "run-1"]
    assert store.artifact_id("run-1") == "artifact-run-1"
    assert store.delete_run("run-1") is True
    assert [row["run_id"] for row in store.list_runs()] == ["run-2"]
    with pytest.raises(DomainValidationError, match="backtest run was not found"):
        store.artifact_id("run-1")


def test_backtest_run_store_preserves_insert_conflict_policies(tmp_path):
    store = BacktestRunStore(tmp_path / "system.db")
    _record(store, "run-1", "2026-02-01T00:00:00+00:00")
    with pytest.raises(sqlite3.IntegrityError):
        _record(store, "run-1", "2026-02-02T00:00:00+00:00")

    store.record_run_if_missing(
        run_id="run-1",
        artifact_id="ignored-artifact",
        strategy_id="momentum",
        start_date="2026-01-01",
        end_date="2026-01-31",
        fingerprint="ignored-fingerprint",
        total_return="0",
        max_drawdown="0",
        created_at="2026-02-03T00:00:00+00:00",
    )
    assert store.artifact_id("run-1") == "artifact-run-1"
