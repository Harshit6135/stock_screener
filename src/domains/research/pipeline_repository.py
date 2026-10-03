"""Research-pipeline schema and persisted stage state."""

from __future__ import annotations

from pathlib import Path

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class ResearchPipelineRepository:
    """Own durable pipeline identities and their current child-job pointers."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        migrate_sqlite(
            self.database,
            "research_pipeline",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS research_pipelines (
                        pipeline_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                        as_of_date TEXT NOT NULL, strategies_json TEXT NOT NULL,
                        created_at TEXT NOT NULL, start_date TEXT, end_date TEXT,
                        trading_dates_json TEXT NOT NULL DEFAULT '[]')""",
                    """CREATE TABLE IF NOT EXISTS research_pipeline_stages (
                        pipeline_id TEXT NOT NULL, stage_name TEXT NOT NULL,
                        job_id INTEGER NOT NULL, PRIMARY KEY(pipeline_id, stage_name),
                        FOREIGN KEY(pipeline_id) REFERENCES research_pipelines(pipeline_id))""",
                ),
            },
        )

    def exists(self, pipeline_id: str) -> bool:
        with sqlite_connection(self.database, read_only=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM research_pipelines WHERE pipeline_id=?", (pipeline_id,)
            ).fetchone()
        return row is not None

    def create(
        self,
        *,
        pipeline_id: str,
        fingerprint: str,
        as_of_date: str,
        strategies_json: str,
        created_at: str,
        start_date: str,
        end_date: str,
        trading_dates_json: str,
        stages: list[tuple[str, int]],
    ) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO research_pipelines
                   (pipeline_id, fingerprint, as_of_date, strategies_json, created_at,
                    start_date, end_date, trading_dates_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pipeline_id,
                    fingerprint,
                    as_of_date,
                    strategies_json,
                    created_at,
                    start_date,
                    end_date,
                    trading_dates_json,
                ),
            )
            connection.executemany(
                "INSERT INTO research_pipeline_stages(pipeline_id, stage_name, job_id) VALUES (?, ?, ?)",
                [(pipeline_id, name, job_id) for name, job_id in stages],
            )

    def set_stage_job(self, pipeline_id: str, stage_name: str, job_id: int) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE research_pipeline_stages SET job_id=? WHERE pipeline_id=? AND stage_name=?",
                (job_id, pipeline_id, stage_name),
            )

    def set_trading_dates(self, pipeline_id: str, trading_dates_json: str) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE research_pipelines SET trading_dates_json=? WHERE pipeline_id=?",
                (trading_dates_json, pipeline_id),
            )

    def add_stages_if_missing(self, pipeline_id: str, stages: list[tuple[str, int]]) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """INSERT OR IGNORE INTO research_pipeline_stages
                   (pipeline_id, stage_name, job_id) VALUES (?, ?, ?)""",
                [(pipeline_id, name, job_id) for name, job_id in stages],
            )

    def pipeline(self, pipeline_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM research_pipelines WHERE pipeline_id=?", (pipeline_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("research pipeline was not found")
        return dict(row)

    def stages(self, pipeline_id: str) -> list[dict[str, object]]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT * FROM research_pipeline_stages WHERE pipeline_id=? ORDER BY stage_name",
                (pipeline_id,),
            ).fetchall()
        return [dict(row) for row in rows]


__all__ = ["ResearchPipelineRepository"]
