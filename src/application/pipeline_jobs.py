"""Durable coordinator for ordered daily research child jobs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.application.jobs import JobStatus, JobStore
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError

_STRATEGIES = {"strategy1", "strategy2"}


class ResearchPipelineJobs:
    def __init__(self, database: str | Path, jobs: JobStore) -> None:
        self.database, self.jobs = Path(database), jobs
        migrate_sqlite(
            self.database,
            "research_pipeline",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS research_pipelines (
                        pipeline_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                        as_of_date TEXT NOT NULL, strategies_json TEXT NOT NULL,
                        created_at TEXT NOT NULL)""",
                    """CREATE TABLE IF NOT EXISTS research_pipeline_stages (
                        pipeline_id TEXT NOT NULL, stage_name TEXT NOT NULL,
                        job_id INTEGER NOT NULL, PRIMARY KEY(pipeline_id, stage_name),
                        FOREIGN KEY(pipeline_id) REFERENCES research_pipelines(pipeline_id))""",
                )
            },
        )

    @staticmethod
    def _request(payload: dict[str, Any]) -> tuple[date, tuple[str, ...]]:
        if (
            not isinstance(payload, dict)
            or set(payload) - {"as_of_date", "strategies"}
            or "as_of_date" not in payload
        ):
            raise DomainValidationError(
                "research pipeline requires as_of_date and optional strategies"
            )
        try:
            as_of_date = date.fromisoformat(str(payload["as_of_date"]))
        except ValueError as exc:
            raise DomainValidationError("as_of_date must be an ISO date") from exc
        if as_of_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("research pipeline requires a completed date")
        strategies_value = payload.get("strategies", ["strategy1", "strategy2"])
        if (
            not isinstance(strategies_value, list)
            or not strategies_value
            or len(strategies_value) != len(set(strategies_value))
            or any(strategy not in _STRATEGIES for strategy in strategies_value)
        ):
            raise DomainValidationError("strategies must be a unique non-empty strategy list")
        return as_of_date, tuple(sorted(strategies_value))

    def submit(self, payload: dict[str, Any]) -> dict[str, object]:
        as_of_date, strategies = self._request(payload)
        normalized = {"as_of_date": as_of_date.isoformat(), "strategies": strategies}
        fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
        pipeline_id = str(uuid5(NAMESPACE_URL, f"research-pipeline:{fingerprint}"))
        with sqlite_connection(self.database, read_only=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM research_pipelines WHERE pipeline_id=?", (pipeline_id,)
            ).fetchone()
        if exists is not None:
            return self.status(pipeline_id)
        child_jobs = []
        for strategy_id in strategies:
            kind = f"research.calculate-{strategy_id}-day"
            child_jobs.append(
                (
                    f"daily:{strategy_id}",
                    self.jobs.submit(
                        f"research-pipeline:{fingerprint}:{kind}",
                        kind,
                        {"as_of_date": as_of_date.isoformat()},
                    ),
                )
            )
        coordinator = self.jobs.submit(
            f"research-pipeline:{fingerprint}:advance",
            "research.pipeline-advance",
            {"pipeline_id": pipeline_id},
        )
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO research_pipelines
                   (pipeline_id, fingerprint, as_of_date, strategies_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    pipeline_id,
                    fingerprint,
                    as_of_date.isoformat(),
                    json.dumps(strategies),
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.executemany(
                "INSERT INTO research_pipeline_stages(pipeline_id, stage_name, job_id) VALUES (?, ?, ?)",
                [(pipeline_id, name, job.job_id) for name, job in child_jobs]
                + [(pipeline_id, "advance", coordinator.job_id)],
            )
        return self.status(pipeline_id)

    def advance(self, payload: dict[str, Any]) -> dict[str, object]:
        if set(payload) != {"pipeline_id"} or not isinstance(payload["pipeline_id"], str):
            raise DomainValidationError("pipeline advance requires pipeline_id")
        pipeline_id = payload["pipeline_id"]
        pipeline = self._pipeline(pipeline_id)
        stages = self._stages(pipeline_id)
        daily = [stage for stage in stages if stage["stage_name"].startswith("daily:")]
        statuses = [self.jobs.get(int(stage["job_id"])).status for stage in daily]
        if any(status in {JobStatus.FAILED, JobStatus.CANCELLED} for status in statuses):
            raise DomainValidationError("research pipeline has a failed daily stage")
        if not all(status == JobStatus.SUCCEEDED for status in statuses):
            raise DomainValidationError("research pipeline daily stages are incomplete")
        as_of_date = date.fromisoformat(str(pipeline["as_of_date"]))
        if as_of_date.weekday() != 4:
            return self.status(pipeline_id)
        strategies = tuple(json.loads(str(pipeline["strategies_json"])))
        weekly_jobs = []
        for strategy_id in strategies:
            name = f"weekly:{strategy_id}"
            if any(stage["stage_name"] == name for stage in stages):
                continue
            kind = f"research.rank-{strategy_id}-week"
            job = self.jobs.submit(
                f"research-pipeline:{pipeline['fingerprint']}:{kind}",
                kind,
                {"week_end": as_of_date.isoformat()},
            )
            weekly_jobs.append((name, job.job_id))
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "INSERT OR IGNORE INTO research_pipeline_stages(pipeline_id, stage_name, job_id) VALUES (?, ?, ?)",
                [(pipeline_id, name, job_id) for name, job_id in weekly_jobs],
            )
        return self.status(pipeline_id)

    def status(self, pipeline_id: str) -> dict[str, object]:
        pipeline = self._pipeline(pipeline_id)
        stages = []
        for stage in self._stages(pipeline_id):
            job = self.jobs.get(int(stage["job_id"]))
            stages.append(
                {"name": stage["stage_name"], "job_id": job.job_id, "status": job.status.value}
            )
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED"}
        state = (
            "FAILED"
            if any(item["status"] in {"FAILED", "CANCELLED"} for item in stages)
            else "SUCCEEDED"
            if stages and all(item["status"] == "SUCCEEDED" for item in stages)
            else "RUNNING"
            if any(item["status"] not in terminal for item in stages)
            else "QUEUED"
        )
        return {
            "pipeline_id": pipeline_id,
            "as_of_date": pipeline["as_of_date"],
            "strategies": json.loads(str(pipeline["strategies_json"])),
            "status": state,
            "stages": stages,
        }

    def _pipeline(self, pipeline_id: str):
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM research_pipelines WHERE pipeline_id=?", (pipeline_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("research pipeline was not found")
        return row

    def _stages(self, pipeline_id: str):
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            return connection.execute(
                "SELECT * FROM research_pipeline_stages WHERE pipeline_id=? ORDER BY stage_name",
                (pipeline_id,),
            ).fetchall()
