"""Durable coordinator for prerequisite data and staged bulk research."""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger("screener." + __name__)
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.domains.indicators import PandasTaAdapter
from src.domains.operations import JobStatus, JobStore
from src.domains.research import ResearchPipelineRepository
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection

_CALCULATION_REVISION = "snapshot-prerequisites"


class ResearchPipelineJobs:
    def __init__(
        self, database: str | Path, jobs: JobStore, runtime: StrategyRuntime | None = None
    ) -> None:
        self.database, self.jobs = Path(database), jobs
        self.runtime = runtime or StrategyRuntime(StrategyDefinitions(database, PandasTaAdapter()))
        if runtime is None:
            self.runtime.seed(Path(__file__).resolve().parents[3] / "strategies")
        self.pipeline_store = ResearchPipelineRepository(self.database)

    def _request(
        self, payload: dict[str, Any]
    ) -> tuple[date, date, tuple[str, ...], tuple[date, ...]]:
        if (
            not isinstance(payload, dict)
            or set(payload)
            - {
                "as_of_date",
                "start_date",
                "end_date",
                "strategies",
                "orchestrate_data",
                "trading_dates",
            }
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
        if start_date > end_date:
            raise DomainValidationError("pipeline start_date must not follow end_date")
        if end_date >= datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise DomainValidationError("research pipeline requires completed dates")
        strategies_value = payload.get("strategies", ["momentum", "positional_trend_following"])
        if not isinstance(payload.get("orchestrate_data", False), bool):
            raise DomainValidationError("orchestrate_data must be boolean")
        if (
            not isinstance(strategies_value, list)
            or not strategies_value
            or len(strategies_value) != len(set(strategies_value))
            or any(strategy not in self.runtime.strategy_ids() for strategy in strategies_value)
        ):
            raise DomainValidationError("pipeline strategies must be known, unique strategy IDs")
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
            sessions = self._market_sessions(start_date, end_date) or tuple(
                start_date + timedelta(days=offset)
                for offset in range((end_date - start_date).days + 1)
                if (start_date + timedelta(days=offset)).weekday() < 5
            )
        return start_date, end_date, tuple(sorted(strategies_value)), sessions

    def _market_sessions(self, start_date: date, end_date: date) -> tuple[date, ...]:
        """Use dates actually present in market data, excluding empty holidays."""
        from src.gates.workflows.trading_calendar import TradingCalendar

        with sqlite_connection(self.database, read_only=True) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_bars'"
            ).fetchone()
            if table is None:
                return ()
        calendar = TradingCalendar(self.database)
        return tuple(calendar.sessions(start_date, end_date))

    def submit(self, payload: dict[str, Any]) -> dict[str, object]:
        start_date, end_date, strategies, trading_dates = self._request(payload)
        normalized = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "strategies": strategies,
            "orchestrate_data": bool(payload.get("orchestrate_data", False)),
            "trading_dates": tuple(item.isoformat() for item in trading_dates),
            "calculation_revision": _CALCULATION_REVISION,
        }
        fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
        pipeline_id = str(uuid5(NAMESPACE_URL, f"research-pipeline:{fingerprint}"))
        if self.pipeline_store.exists(pipeline_id):
            return self.status(pipeline_id)
        child_jobs = []
        if normalized["orchestrate_data"]:
            child_jobs.append(
                (
                    "market:prepare",
                    self.jobs.submit(
                        f"research-pipeline:{fingerprint}:prepare",
                        "research.pipeline-prepare",
                        {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
                    ),
                )
            )
        else:
            if not trading_dates:
                raise DomainValidationError("bulk research requires explicit trading_dates")
            factor_strategies = [
                strategy
                for strategy in strategies
                if self.runtime.strategy_kind(strategy) == "factor_score"
            ]
            event_strategies = [
                strategy
                for strategy in strategies
                if self.runtime.strategy_kind(strategy) == "event_signal"
            ]
            if factor_strategies:
                child_jobs.append(
                    (
                        "research:factor-bulk",
                        self.jobs.submit(
                            f"research-pipeline:{fingerprint}:factor-bulk",
                            "research.rebuild-range",
                            {
                                "start_date": start_date.isoformat(),
                                "end_date": end_date.isoformat(),
                                "strategies": factor_strategies,
                                "trading_dates": [item.isoformat() for item in trading_dates],
                            },
                            max_attempts=2,
                        ),
                    )
                )
            if event_strategies:
                child_jobs.append(
                    (
                        "research:event-signals",
                        self.jobs.submit(
                            f"research-pipeline:{fingerprint}:event-signals",
                            "research.positional-trend-build-range",
                            {
                                "trading_dates": [item.isoformat() for item in trading_dates],
                                "universe": "SNAPSHOT_NIFTY500",
                            },
                            max_attempts=2,
                        ),
                    )
                )
        coordinator = (
            self.jobs.submit(
                f"research-pipeline:{fingerprint}:advance",
                "research.pipeline-advance",
                {"pipeline_id": pipeline_id},
            )
            if normalized["orchestrate_data"]
            else None
        )
        self.pipeline_store.create(
            pipeline_id=pipeline_id,
            fingerprint=fingerprint,
            as_of_date=end_date.isoformat(),
            strategies_json=json.dumps(strategies),
            created_at=datetime.now(UTC).isoformat(),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            trading_dates_json=json.dumps([item.isoformat() for item in trading_dates]),
            stages=[(name, job.job_id) for name, job in child_jobs]
            + ([("advance", coordinator.job_id)] if coordinator else []),
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
        self.pipeline_store.set_stage_job(pipeline_id, "advance", job.job_id)
        return self.status(pipeline_id) | {"deferred": True}

    def advance(self, payload: dict[str, Any]) -> dict[str, object]:
        if set(payload) != {"pipeline_id"} or not isinstance(payload["pipeline_id"], str):
            raise DomainValidationError("pipeline advance requires pipeline_id")
        pipeline_id = payload["pipeline_id"]
        pipeline = self._pipeline(pipeline_id)
        stages = self._stages(pipeline_id)
        data_stages = [
            stage
            for stage in stages
            if str(stage["stage_name"]).startswith(("reference:", "market:"))
        ]
        data_statuses = [self.jobs.get(int(stage["job_id"])).status for stage in data_stages]
        if any(status in {JobStatus.FAILED, JobStatus.CANCELLED} for status in data_statuses):
            raise DomainValidationError("research pipeline has a failed data stage")
        if not all(status == JobStatus.SUCCEEDED for status in data_statuses):
            return self._defer_advance(pipeline_id, str(pipeline["fingerprint"]))

        # Check any spawned child bar jobs from market:refresh
        market_stage = next(
            (stage for stage in data_stages if stage["stage_name"] == "market:refresh"), None
        )
        if market_stage is not None:
            market_job = self.jobs.get(int(market_stage["job_id"]))
            if market_job.result and isinstance(market_job.result.get("job_ids"), list):
                child_bar_jobs = [self.jobs.get(int(jid)) for jid in market_job.result["job_ids"]]
                if any(
                    job.status in {JobStatus.FAILED, JobStatus.CANCELLED} for job in child_bar_jobs
                ):
                    raise DomainValidationError("research pipeline has a failed data stage")
                if not all(job.status == JobStatus.SUCCEEDED for job in child_bar_jobs):
                    return self._defer_advance(pipeline_id, str(pipeline["fingerprint"]))

        start_date = date.fromisoformat(str(pipeline["start_date"] or pipeline["as_of_date"]))
        end_date = date.fromisoformat(str(pipeline["end_date"] or pipeline["as_of_date"]))
        strategies = tuple(json.loads(str(pipeline["strategies_json"])))
        if any(str(stage["stage_name"]).startswith("research:") for stage in stages):
            return self.status(pipeline_id)
        sessions = [item.isoformat() for item in self._market_sessions(start_date, end_date)]
        if sessions:
            self.pipeline_store.set_trading_dates(pipeline_id, json.dumps(sessions))
        else:
            sessions = json.loads(str(pipeline["trading_dates_json"]))
        if not sessions:
            raise DomainValidationError("research pipeline has no explicit trading sessions")
        factor_strategies = [
            strategy
            for strategy in strategies
            if self.runtime.strategy_kind(strategy) == "factor_score"
        ]
        event_strategies = [
            strategy
            for strategy in strategies
            if self.runtime.strategy_kind(strategy) == "event_signal"
        ]
        jobs_to_add = []
        if factor_strategies:
            jobs_to_add.append(
                (
                    "research:factor-bulk",
                    self.jobs.submit(
                        f"research-pipeline:{pipeline['fingerprint']}:factor-bulk",
                        "research.rebuild-range",
                        {
                            "start_date": start_date.isoformat(),
                            "end_date": end_date.isoformat(),
                            "strategies": factor_strategies,
                            "trading_dates": sessions,
                        },
                        max_attempts=2,
                    ),
                )
            )
        if event_strategies:
            jobs_to_add.append(
                (
                    "research:event-signals",
                    self.jobs.submit(
                        f"research-pipeline:{pipeline['fingerprint']}:event-signals",
                        "research.positional-trend-build-range",
                        {"trading_dates": sessions, "universe": "SNAPSHOT_NIFTY500"},
                        max_attempts=2,
                    ),
                )
            )
        self.pipeline_store.add_stages_if_missing(
            pipeline_id, [(name, job.job_id) for name, job in jobs_to_add]
        )
        return self.status(pipeline_id)

    def retry_stage(self, pipeline_id: str, stage_name: str) -> dict[str, object]:
        """Retry one failed or cancelled pipeline stage, leaving others intact."""
        pipeline = self._pipeline(pipeline_id)
        stage = next(
            (item for item in self._stages(pipeline_id) if item["stage_name"] == stage_name),
            None,
        )
        if stage is None:
            raise DomainValidationError("pipeline stage was not found")
        stage_job_id = int(stage["job_id"])
        stage_job = self.jobs.get(stage_job_id)
        if stage_job.status == JobStatus.CANCELLED:
            job = self.jobs.retry_cancelled(stage_job_id)
        else:
            job = self.jobs.retry_failed(stage_job_id)
        return self.status(str(pipeline["pipeline_id"])) | {
            "retried_stage": stage_name,
            "job": job.job_id,
        }

    def cancel(self, pipeline_id: str) -> dict[str, object]:
        """Request cancellation for all non-terminal child jobs."""
        pipeline = self._pipeline(pipeline_id)
        cancelled: list[str] = []
        for stage in self._stages(pipeline_id):
            job = self.jobs.get(int(stage["job_id"]))
            if job.status not in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
                self.jobs.request_cancel(job.job_id)
                cancelled.append(str(stage["stage_name"]))
            if (
                stage["stage_name"] == "market:refresh"
                and job.result
                and isinstance(job.result.get("job_ids"), list)
            ):
                for jid in job.result["job_ids"]:
                    child_job = self.jobs.get(int(jid))
                    if child_job.status not in {
                        JobStatus.SUCCEEDED,
                        JobStatus.FAILED,
                        JobStatus.CANCELLED,
                    }:
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
        market_stage = next(
            (
                stage
                for stage in self._stages(pipeline_id)
                if stage["stage_name"] == "market:refresh"
            ),
            None,
        )
        market_data_summary = None
        if market_stage is not None:
            market_job = self.jobs.get(int(market_stage["job_id"]))
            if market_job.result and isinstance(market_job.result.get("job_ids"), list):
                child_bar_jobs = [self.jobs.get(int(jid)) for jid in market_job.result["job_ids"]]
                bar_total = len(child_bar_jobs)
                bar_succeeded = sum(1 for j in child_bar_jobs if j.status == JobStatus.SUCCEEDED)
                bar_failed = sum(
                    1 for j in child_bar_jobs if j.status in {JobStatus.FAILED, JobStatus.CANCELLED}
                )
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
        return self.pipeline_store.pipeline(pipeline_id)

    def _stages(self, pipeline_id: str):
        return self.pipeline_store.stages(pipeline_id)
