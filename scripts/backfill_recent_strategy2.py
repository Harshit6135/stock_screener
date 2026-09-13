"""Publish Strategy 2 scores for recent sessions from persisted v4 market data."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from run import create_app
from src.application.operations import sqlite_backup


def _run(services, kind: str, payload: dict[str, str], fingerprint: str) -> dict:
    job = services.jobs.submit(fingerprint, kind, payload, max_attempts=1)
    if job.result is not None:
        return job.result
    if job.status.value != "QUEUED":
        raise RuntimeError(f"job is not queued: {kind}")
    completed = services.worker.run_once()
    if completed is None or completed.job_id != job.job_id or completed.result is None:
        print(
            f"strategy2_job_failed kind={kind} "
            f"error_class={completed.last_error if completed else 'none'}",
            file=sys.stderr,
        )
        raise RuntimeError("Strategy 2 job failed")
    return completed.result


def main() -> int:
    app = create_app()
    services = app.extensions["screener_services"]
    backup = (
        Path(app.config["DATA_DIRECTORY"])
        / "backups"
        / f"system-before-strategy2-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.db"
    )
    sqlite_backup(services.database, backup)
    print(f"strategy2_database_backup={backup.name}", flush=True)
    as_of = date(2026, 9, 11)
    first = _run(
        services,
        "research.calculate-strategy2-day",
        {"as_of_date": as_of.isoformat()},
        f"recent-backfill:strategy2-v4-port-1:{as_of}",
    )
    response = app.test_client().get(
        f"/api/v2/research/features/{first['feature_artifact_id']}?strategy_id=strategy2"
    )
    if response.status_code != 200 or response.json["data"]["strategy_id"] != "strategy2":
        raise RuntimeError("Strategy 2 feature artifact readback failed")
    print(f"strategy2_scored_date={as_of} count={first['scored_count']}", flush=True)
    if "--all" not in sys.argv:
        return 0
    reliance_id = str(services.market.instrument("RELIANCE")["instrument_id"])
    recent = services.market.bars(reliance_id, as_of - timedelta(days=25), as_of)
    trading_dates = [str(row["as_of_date"]) for row in recent][-10:]
    if len(trading_dates) != 10:
        raise RuntimeError("ten market sessions are required")
    for day in trading_dates[:-1]:
        result = _run(
            services,
            "research.calculate-strategy2-day",
            {"as_of_date": day},
            f"recent-backfill:strategy2-v4-port-1:{day}",
        )
        print(f"strategy2_scored_date={day} count={result['scored_count']}", flush=True)
    for week_end in (date(2026, 9, 4), date(2026, 9, 11)):
        result = _run(
            services,
            "research.rank-strategy2-week",
            {"week_end": week_end.isoformat()},
            f"recent-backfill:strategy2-v4-port-1-week:{week_end}",
        )
        response = app.test_client().get(
            f"/api/v2/research/rankings?week_end={week_end}&strategy_id=strategy2&limit=20"
        )
        if response.status_code != 200 or len(response.json["members"]) != 20:
            raise RuntimeError("Strategy 2 ranking API readback failed")
        print(f"strategy2_ranked_week={week_end} count={result['ranked_count']}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - keep broker and local paths private
        print(f"Strategy 2 backfill failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
