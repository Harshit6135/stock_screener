"""Repair the one failed symbol and supersede preliminary research artifacts."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any

from run import create_app
from src.application.sqlite import sqlite_connection


def _old_result(database: Any, fingerprint: str) -> dict[str, object] | None:
    with sqlite_connection(database, read_only=True, row_factory=True) as connection:
        row = connection.execute(
            "SELECT result_json FROM ops_jobs WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
    return json.loads(row["result_json"]) if row and row["result_json"] else None


def _run(
    services: Any, kind: str, payload: dict[str, object], fingerprint: str
) -> dict[str, object]:
    job = services.jobs.submit(fingerprint, kind, payload, max_attempts=1)
    if job.result is not None:
        return job.result
    completed = services.worker.run_once()
    if completed is None or completed.job_id != job.job_id or completed.result is None:
        print(
            f"finalize_job_failed kind={kind} "
            f"error_class={completed.last_error if completed else 'none'}",
            file=sys.stderr,
        )
        raise RuntimeError("research finalization job failed")
    return completed.result


def main() -> int:
    app = create_app()
    services = app.extensions["screener_services"]
    today = datetime.now(UTC).date()
    for kind, payload, fingerprint in (
        (
            "market.import-v3-bars",
            {"symbol": "M&MFIN", "start_date": "2025-07-18", "end_date": "2026-07-17"},
            "recent-backfill:v3:M&MFIN:retry1",
        ),
        (
            "market.fetch-kite-bars",
            {"symbol": "M&MFIN", "start_date": "2026-07-18", "end_date": today.isoformat()},
            f"recent-backfill:kite:M&MFIN:{today}:retry1",
        ),
    ):
        result = _run(services, kind, payload, fingerprint)
        print(f"repaired={kind} count={result['bar_count']}", flush=True)
    reliance = services.market.instrument("RELIANCE")
    recent = services.market.bars(str(reliance["instrument_id"]), today - timedelta(days=25), today)
    trading_dates = [str(item["as_of_date"]) for item in recent][-10:]
    if len(trading_dates) != 10:
        raise RuntimeError("ten completed sessions are required")
    for as_of_date in trading_dates:
        old = _old_result(services.database, f"recent-backfill:strategy1:{as_of_date}")
        new = _run(
            services,
            "research.calculate-strategy1-day",
            {"as_of_date": as_of_date},
            f"recent-backfill:strategy1-v4-port-2:{as_of_date}",
        )
        if old is not None:
            # One preliminary failed finalization qualified these two new
            # artifacts before the catalog branch traversal was corrected.
            for key in ("percentile_artifact_id", "score_artifact_id"):
                services.catalog.set_status(
                    str(new[key]), "VALID", "corrected replacement-branch invalidation"
                )
            for key in ("feature_artifact_id", "percentile_artifact_id", "score_artifact_id"):
                services.catalog.supersede(str(old[key]), str(new[key]))
        print(f"final_scored_date={as_of_date} count={new['scored_count']}", flush=True)
    week_ends = sorted(
        {
            date.fromisoformat(value) + timedelta(days=4 - date.fromisoformat(value).weekday())
            for value in trading_dates
        }
    )
    for week_end in week_ends:
        if week_end >= today:
            continue
        old = _old_result(services.database, f"recent-backfill:strategy1-week:{week_end}")
        new = _run(
            services,
            "research.rank-strategy1-week",
            {"week_end": week_end.isoformat()},
            f"recent-backfill:strategy1-v4-port-2-week:{week_end}",
        )
        if old is not None:
            services.catalog.supersede(str(old["artifact_id"]), str(new["artifact_id"]))
        response = app.test_client().get(
            f"/api/v2/research/rankings?week_end={week_end.isoformat()}&limit=20"
        )
        if response.status_code != 200 or not response.json["members"]:
            raise RuntimeError("final ranking API readback failed")
        print(f"final_ranked_week={week_end} count={new['ranked_count']}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - do not emit provider or credential details
        print(f"Recent research finalization failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
