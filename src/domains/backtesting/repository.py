"""Backtesting-owned run records and index persistence."""

from __future__ import annotations

from pathlib import Path

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class BacktestRunStore:
    """Persistence for immutable backtest results and their operational index."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        migrate_sqlite(
            self.database,
            "backtest",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS backtest_runs (
                        run_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL,
                        strategy_id TEXT NOT NULL, start_date TEXT NOT NULL,
                        end_date TEXT NOT NULL, fingerprint TEXT NOT NULL,
                        total_return TEXT NOT NULL, max_drawdown TEXT NOT NULL,
                        created_at TEXT NOT NULL)""",
                    "CREATE INDEX IF NOT EXISTS backtest_runs_dates ON backtest_runs(start_date, end_date)",
                )
            },
        )

    def record_run(
        self,
        *,
        run_id: str,
        artifact_id: str,
        strategy_id: str,
        start_date: str,
        end_date: str,
        fingerprint: str,
        total_return: str,
        max_drawdown: str,
        created_at: str,
    ) -> None:
        self._insert_run(
            "INSERT INTO",
            run_id=run_id,
            artifact_id=artifact_id,
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            fingerprint=fingerprint,
            total_return=total_return,
            max_drawdown=max_drawdown,
            created_at=created_at,
        )

    def record_run_if_missing(
        self,
        *,
        run_id: str,
        artifact_id: str,
        strategy_id: str,
        start_date: str,
        end_date: str,
        fingerprint: str,
        total_return: str,
        max_drawdown: str,
        created_at: str,
    ) -> None:
        self._insert_run(
            "INSERT OR IGNORE INTO",
            run_id=run_id,
            artifact_id=artifact_id,
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            fingerprint=fingerprint,
            total_return=total_return,
            max_drawdown=max_drawdown,
            created_at=created_at,
        )

    def _insert_run(
        self,
        insert_sql: str,
        *,
        run_id: str,
        artifact_id: str,
        strategy_id: str,
        start_date: str,
        end_date: str,
        fingerprint: str,
        total_return: str,
        max_drawdown: str,
        created_at: str,
    ) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute(
                f"""{insert_sql} backtest_runs
                   (run_id, artifact_id, strategy_id, start_date, end_date,
                    fingerprint, total_return, max_drawdown, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    artifact_id,
                    strategy_id,
                    start_date,
                    end_date,
                    fingerprint,
                    total_return,
                    max_drawdown,
                    created_at,
                ),
            )

    def list_runs(self, limit: int = 50) -> list[dict[str, object]]:
        if not 1 <= limit <= 100:
            raise DomainValidationError("backtest limit must be 1..100")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def artifact_id(self, run_id: str) -> str:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT artifact_id FROM backtest_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("backtest run was not found")
        return str(row["artifact_id"])

    def delete_run(self, run_id: str) -> bool:
        """Remove an index row while leaving its immutable artifact untouched."""
        with sqlite_connection(self.database) as connection:
            cursor = connection.execute("DELETE FROM backtest_runs WHERE run_id=?", (run_id,))
        if cursor.rowcount == 0:
            raise DomainValidationError("backtest run was not found")
        return True
