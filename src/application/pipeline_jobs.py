"""Durable coordinator for ordered daily research child jobs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.application.jobs import JobStatus, JobStore
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.application.strategy_definitions import StrategyDefinitions
from src.application.strategy_runtime import StrategyRuntime
from src.indicators.registry import PandasTaAdapter
from src.platform_kernel import DomainValidationError

_CALCULATION_REVISION = "historical-universe-v2"


class ResearchPipelineJobs:
    def __init__(self, database: str | Path, jobs: JobStore, runtime: StrategyRuntime | None = None) -> None:
        self.database, self.jobs = Path(database), jobs
        self.runtime = runtime or StrategyRuntime(StrategyDefinitions(database, PandasTaAdapter()))
        if runtime is None:
            self.runtime.seed(Path(__file__).resolve().parents[2] / "strategies")
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
                ,2: (
                    "ALTER TABLE research_pipelines ADD COLUMN start_date TEXT",
                    "ALTER TABLE research_pipelines ADD COLUMN end_date TEXT",
                )
            },
        )

    def _request(self, payload: dict[str, Any]) -> tuple[date, date, tuple[str, ...], tuple[date, ...]]:
        if (
            not isinstance(payload, dict)
            or set(payload) - {"as_of_date", "start_date", "end_date", "strategies", "orchestrate_data", "trading_dates"}
            or ("as_of_date" not in payload and not {"start_date", "end_date"}.issubset(payload))
        ):
            raise DomainValidationError("research pipeline requires a date or start/end range")
        try:
            if "as_of_date" in payload:
                start_date = end_date = date.fromisoformat(str(payload["as_of_date"]))
            else:
                start_date = date.fromisoformat(str(payload["start_date"]))
                end_date = date.fromisoformat(str(payload["end_date"]))
        except ValueError as exc:
            raise DomainValidationError("pipeline dates must be ISO dates") from exc
        if start_date > end_date or (end_date - start_date).days > 365:
            raise DomainValidationError("pipeline date range must be at most 365 days")
        if end_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("research pipeline requires completed dates")
        strategies_value = payload.get("strategies", list(self.runtime.strategy_ids()))
        if not isinstance(payload.get("orchestrate_data", False), bool):
            raise DomainValidationError("orchestrate_data must be boolean")
        if (
            not isinstance(strategies_value, list)
            or not strategies_value
            or len(strategies_value) != len(set(strategies_value))
            or any(strategy not in self.runtime.strategy_ids() for strategy in strategies_value)
        ):
            raise DomainValidationError("strategies must be a unique non-empty strategy list")
        trading_dates = payload.get("trading_dates")
        if trading_dates is not None:
            if not isinstance(trading_dates, list):
                raise DomainValidationError("trading_dates must be a list")
            try:
                sessions = tuple(sorted({date.fromisoformat(str(item)) for item in trading_dates}))
            except ValueError as exc:
                raise DomainValidationError("trading_dates must be ISO dates") from exc
            if any(item < start_date or item > end_date for item in sessions):
                raise DomainValidationError("trading_dates must be within the pipeline range")
        else:
            sessions = ()
        return start_date, end_date, tuple(sorted(strategies_value)), sessions

    def submit(self, payload: dict[str, Any]) -> dict[str, object]:
        start_date, end_date, strategies, trading_dates = self._request(payload)
        normalized = {
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "strategies": strategies, "orchestrate_data": bool(payload.get("orchestrate_data", False)),
            "trading_dates": tuple(item.isoformat() for item in trading_dates),
            "calculation_revision": _CALCULATION_REVISION,
        }
        fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
        pipeline_id = str(uuid5(NAMESPACE_URL, f"research-pipeline:{fingerprint}"))
        with sqlite_connection(self.database, read_only=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM research_pipelines WHERE pipeline_id=?", (pipeline_id,)
            ).fetchone()
        if exists is not None:
            return self.status(pipeline_id)
        child_jobs = []
        if normalized["orchestrate_data"]:
            child_jobs.extend([
                ("reference:sync", self.jobs.submit(
                    f"research-pipeline:{fingerprint}:reference-sync", "reference.sync-kite-instruments", {},
                )),
                ("market:refresh", self.jobs.submit(
                    f"research-pipeline:{fingerprint}:market-refresh", "market.schedule-all-symbol-refresh",
                    {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
                )),
                ("reference:reconcile", self.jobs.submit(
                    f"research-pipeline:{fingerprint}:reference-reconcile", "reference.reconcile-market",
                    {"as_of_date": end_date.isoformat()},
                )),
            ])
        else:
            dates = trading_dates or tuple(
                start_date + timedelta(days=offset)
                for offset in range((end_date - start_date).days + 1)
                if (start_date + timedelta(days=offset)).weekday() < 5
            )
            for strategy_id in strategies:
                for session in dates:
                    kind = "research.calculate-day"
                    name = f"daily:{strategy_id}" if start_date == end_date else f"daily:{strategy_id}:{session.isoformat()}"
                    child_jobs.append((name, self.jobs.submit(
                        f"research-pipeline:{fingerprint}:{kind}:{strategy_id}:{session.isoformat()}", kind,
                        {"as_of_date": session.isoformat(), "strategy_id": strategy_id},
                    )))
        coordinator = self.jobs.submit(
            f"research-pipeline:{fingerprint}:advance",
            "research.pipeline-advance",
            {"pipeline_id": pipeline_id},
        )
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO research_pipelines
                   (pipeline_id, fingerprint, as_of_date, strategies_json, created_at, start_date, end_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    pipeline_id,
                    fingerprint,
                    end_date.isoformat(),
                    json.dumps(strategies),
                    datetime.now(UTC).isoformat(),
                    start_date.isoformat(),
                    end_date.isoformat(),
                ),
            )
            connection.executemany(
                "INSERT INTO research_pipeline_stages(pipeline_id, stage_name, job_id) VALUES (?, ?, ?)",
                [(pipeline_id, name, job.job_id) for name, job in child_jobs]
                + [(pipeline_id, "advance", coordinator.job_id)],
            )
        return self.status(pipeline_id)

    def _defer_advance(self, pipeline_id: str, fingerprint: str) -> dict[str, object]:
        """Queue the next coordinator pass after work already queued ahead of it.

        Job workers complete handlers atomically.  A coordinator therefore must
        not fail merely because its prerequisite jobs are still queued.  Moving
        the stage pointer to a successor lets the worker drain those jobs first
        and then revisit the pipeline without claiming completion early.
        """
        job = self.jobs.submit(
            f"research-pipeline:{fingerprint}:advance:{uuid5(NAMESPACE_URL, str(datetime.now(UTC).timestamp()))}",
            "research.pipeline-advance",
            {"pipeline_id": pipeline_id},
            delay_seconds=30,
        )
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE research_pipeline_stages SET job_id=? WHERE pipeline_id=? AND stage_name='advance'",
                (job.job_id, pipeline_id),
            )
        return self.status(pipeline_id) | {"deferred": True}

    def advance(self, payload: dict[str, Any]) -> dict[str, object]:
        if set(payload) != {"pipeline_id"} or not isinstance(payload["pipeline_id"], str):
            raise DomainValidationError("pipeline advance requires pipeline_id")
        pipeline_id = payload["pipeline_id"]
        pipeline = self._pipeline(pipeline_id)
        stages = self._stages(pipeline_id)
        data_stages = [stage for stage in stages if str(stage["stage_name"]).startswith(("reference:", "market:"))]
        data_statuses = [self.jobs.get(int(stage["job_id"])).status for stage in data_stages]
        if any(status in {JobStatus.FAILED, JobStatus.CANCELLED} for status in data_statuses):
            raise DomainValidationError("research pipeline has a failed data stage")
        if not all(status == JobStatus.SUCCEEDED for status in data_statuses):
            return self._defer_advance(pipeline_id, str(pipeline["fingerprint"]))

        # Check any spawned child bar jobs from market:refresh
        market_stage = next((stage for stage in data_stages if stage["stage_name"] == "market:refresh"), None)
        if market_stage is not None:
            market_job = self.jobs.get(int(market_stage["job_id"]))
            if market_job.result and isinstance(market_job.result.get("job_ids"), list):
                child_bar_jobs = [self.jobs.get(int(jid)) for jid in market_job.result["job_ids"]]
                if any(job.status in {JobStatus.FAILED, JobStatus.CANCELLED} for job in child_bar_jobs):
                    raise DomainValidationError("research pipeline has a failed data stage")
                if not all(job.status == JobStatus.SUCCEEDED for job in child_bar_jobs):
                    return self._defer_advance(pipeline_id, str(pipeline["fingerprint"]))

        daily = [stage for stage in stages if stage["stage_name"].startswith("daily:")]
        start_date = date.fromisoformat(str(pipeline["start_date"] or pipeline["as_of_date"]))
        end_date = date.fromisoformat(str(pipeline["end_date"] or pipeline["as_of_date"]))
        strategies = tuple(json.loads(str(pipeline["strategies_json"])))

        # If data stages completed and daily stages haven't been queued yet, queue daily stages now
        if not daily:
            trading_dates = tuple(
                start_date + timedelta(days=offset)
                for offset in range((end_date - start_date).days + 1)
                if (start_date + timedelta(days=offset)).weekday() < 5
            )
            daily_jobs = []
            for strategy_id in strategies:
                for session in trading_dates:
                    kind = "research.calculate-day"
                    name = f"daily:{strategy_id}" if start_date == end_date else f"daily:{strategy_id}:{session.isoformat()}"
                    job = self.jobs.submit(
                        f"research-pipeline:{pipeline['fingerprint']}:{kind}:{strategy_id}:{session.isoformat()}", kind,
                        {"as_of_date": session.isoformat(), "strategy_id": strategy_id},
                    )
                    daily_jobs.append((name, job.job_id))
            with sqlite_connection(self.database) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.executemany(
                    "INSERT OR IGNORE INTO research_pipeline_stages(pipeline_id, stage_name, job_id) VALUES (?, ?, ?)",
                    [(pipeline_id, name, job_id) for name, job_id in daily_jobs],
                )
            return self._defer_advance(pipeline_id, str(pipeline["fingerprint"]))

        statuses = [self.jobs.get(int(stage["job_id"])).status for stage in daily]
        if any(status in {JobStatus.FAILED, JobStatus.CANCELLED} for status in statuses):
            raise DomainValidationError("research pipeline has a failed daily stage")
        if not all(status == JobStatus.SUCCEEDED for status in statuses):
            return self._defer_advance(pipeline_id, str(pipeline["fingerprint"]))

        sessions = sorted(
            {
                date.fromisoformat(str(self.jobs.get(int(stage["job_id"])).payload["as_of_date"]))
                for stage in daily
            }
        )
        week_ends = tuple(
            max(day for day in sessions if day.isocalendar()[:2] == week)
            for week in sorted({day.isocalendar()[:2] for day in sessions})
        )
        if not week_ends:
            return self.status(pipeline_id)
        weekly_jobs = []
        for strategy_id in strategies:
            for week_end in week_ends:
                name = f"weekly:{strategy_id}" if len(week_ends) == 1 and start_date == end_date else f"weekly:{strategy_id}:{week_end.isoformat()}"
                if any(stage["stage_name"] == name for stage in stages):
                    continue
                kind = "research.rank-week"
                job = self.jobs.submit(f"research-pipeline:{pipeline['fingerprint']}:{kind}:{strategy_id}:{week_end.isoformat()}", kind, {"week_end": week_end.isoformat(), "strategy_id": strategy_id})
                weekly_jobs.append((name, job.job_id))
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "INSERT OR IGNORE INTO research_pipeline_stages(pipeline_id, stage_name, job_id) VALUES (?, ?, ?)",
                [(pipeline_id, name, job_id) for name, job_id in weekly_jobs],
            )
        return self.status(pipeline_id)

    def retry_stage(self, pipeline_id: str, stage_name: str) -> dict[str, object]:
        """Retry one failed pipeline stage and leave every other stage intact."""
        pipeline = self._pipeline(pipeline_id)
        stage = next(
            (item for item in self._stages(pipeline_id) if item["stage_name"] == stage_name),
            None,
        )
        if stage is None:
            raise DomainValidationError("pipeline stage was not found")
        job = self.jobs.retry_failed(int(stage["job_id"]))
        return self.status(str(pipeline["pipeline_id"])) | {"retried_stage": stage_name, "job": job.job_id}

    def cancel(self, pipeline_id: str) -> dict[str, object]:
        """Request cancellation for all non-terminal child jobs."""
        pipeline = self._pipeline(pipeline_id)
        cancelled: list[str] = []
        for stage in self._stages(pipeline_id):
            job = self.jobs.get(int(stage["job_id"]))
            if job.status not in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
                self.jobs.request_cancel(job.job_id)
                cancelled.append(str(stage["stage_name"]))
            if stage["stage_name"] == "market:refresh" and job.result and isinstance(job.result.get("job_ids"), list):
                for jid in job.result["job_ids"]:
                    child_job = self.jobs.get(int(jid))
                    if child_job.status not in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
                        self.jobs.request_cancel(child_job.job_id)
        return self.status(str(pipeline["pipeline_id"])) | {"cancelled_stages": cancelled}

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
        market_stage = next((stage for stage in self._stages(pipeline_id) if stage["stage_name"] == "market:refresh"), None)
        market_data_summary = None
        if market_stage is not None:
            market_job = self.jobs.get(int(market_stage["job_id"]))
            if market_job.result and isinstance(market_job.result.get("job_ids"), list):
                child_bar_jobs = [self.jobs.get(int(jid)) for jid in market_job.result["job_ids"]]
                bar_total = len(child_bar_jobs)
                bar_succeeded = sum(1 for j in child_bar_jobs if j.status == JobStatus.SUCCEEDED)
                bar_failed = sum(1 for j in child_bar_jobs if j.status in {JobStatus.FAILED, JobStatus.CANCELLED})
                bar_pending = bar_total - bar_succeeded - bar_failed
                market_data_summary = {
                    "total_bars": bar_total,
                    "succeeded": bar_succeeded,
                    "failed": bar_failed,
                    "pending": bar_pending,
                }
                if bar_failed > 0:
                    state = "FAILED"
                elif bar_pending > 0 and state == "SUCCEEDED":
                    state = "RUNNING"
        result: dict[str, object] = {
            "pipeline_id": pipeline_id,
            "as_of_date": pipeline["as_of_date"],
            "start_date": pipeline["start_date"] or pipeline["as_of_date"],
            "end_date": pipeline["end_date"] or pipeline["as_of_date"],
            "strategies": json.loads(str(pipeline["strategies_json"])),
            "status": state,
            "stages": stages,
        }
        if market_data_summary is not None:
            result["market_data"] = market_data_summary
        return result

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
