"""Resumeable read-only v3/Kite backfill into v4 through 10 completed sessions.

This writes only v4 instance data. V3 market_data.db is opened read-only.
It does not invoke broker order methods. Re-running reuses successful jobs.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from run import create_app
from src.application.operations import sqlite_backup

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_DATABASE = PROJECT_ROOT / "instance" / "market_data.db"
V4_DATABASE = PROJECT_ROOT / "instance" / "system.db"
SYMBOL_INTERVAL_SECONDS = 0.45


def _run(
    services: Any, kind: str, payload: dict[str, object], fingerprint: str
) -> dict[str, object] | None:
    job = services.jobs.submit(fingerprint, kind, payload, max_attempts=1)
    if job.result is not None:
        return job.result
    if job.status.value != "QUEUED":
        return None
    completed = services.worker.run_once()
    if completed is None or completed.job_id != job.job_id:
        raise RuntimeError("worker claimed a different job; stop the backfill")
    if completed.result is None:
        print(
            f"failed kind={kind} status={completed.status.value} error_class={completed.last_error}",
            flush=True,
        )
    return completed.result


def _legacy_symbols() -> tuple[str, ...]:
    if not LEGACY_DATABASE.is_file():
        raise RuntimeError("legacy market_data.db is unavailable")
    with sqlite3.connect(
        f"file:{LEGACY_DATABASE.resolve().as_posix()}?mode=ro", uri=True
    ) as connection:
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT tradingsymbol FROM market_data WHERE date='2026-07-17' ORDER BY tradingsymbol"
            )
        )


def main() -> int:
    if V4_DATABASE.is_file():
        backup = (
            PROJECT_ROOT
            / "instance"
            / "backups"
            / f"system-before-research-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.db"
        )
        sqlite_backup(V4_DATABASE, backup)
        print(f"v4_database_backup={backup.name}", flush=True)
    app = create_app()
    services = app.extensions["screener_services"]
    today = datetime.now(UTC).date()
    sync = _run(services, "reference.sync-kite-instruments", {}, f"recent-backfill:sync:{today}")
    if sync is None:
        raise RuntimeError("Kite instrument sync failed")
    print(f"matched_instruments={sync['matched_count']}", flush=True)
    available: set[str] = set()
    offset = 0
    while True:
        page = services.market.instruments(limit=500, offset=offset)
        if not page:
            break
        available.update(str(item["symbol"]) for item in page)
        offset += len(page)
    symbols = [symbol for symbol in _legacy_symbols() if symbol in available]
    imported = 0
    refreshed = 0
    failures: list[str] = []
    for index, symbol in enumerate(symbols, start=1):
        legacy = _run(
            services,
            "market.import-v3-bars",
            {"symbol": symbol, "start_date": "2025-07-18", "end_date": "2026-07-17"},
            f"recent-backfill:v3:{symbol}",
        )
        if legacy is None:
            failures.append(f"{symbol}:v3")
            continue
        imported += 1
        recent = _run(
            services,
            "market.fetch-kite-bars",
            {"symbol": symbol, "start_date": "2026-07-18", "end_date": today.isoformat()},
            f"recent-backfill:kite:{symbol}:{today}",
        )
        if recent is None:
            failures.append(f"{symbol}:kite")
        else:
            refreshed += 1
        if index % 100 == 0 or index == len(symbols):
            print(
                f"progress={index}/{len(symbols)} imported={imported} "
                f"kite_refreshed={refreshed} failures={len(failures)}",
                flush=True,
            )
        time.sleep(SYMBOL_INTERVAL_SECONDS)
    reliance = services.market.instrument("RELIANCE")
    recent_bars = services.market.bars(
        str(reliance["instrument_id"]), today - timedelta(days=25), today
    )
    trading_dates = [str(item["as_of_date"]) for item in recent_bars][-10:]
    if len(trading_dates) != 10:
        raise RuntimeError("fewer than 10 completed trading dates are available")
    daily: list[dict[str, object]] = []
    for session_date in trading_dates:
        result = _run(
            services,
            "research.calculate-strategy1-day",
            {"as_of_date": session_date},
            f"recent-backfill:strategy1:{session_date}",
        )
        if result is None:
            raise RuntimeError(f"Strategy 1 calculation failed for {session_date}")
        daily.append(result)
        print(f"scored_date={session_date} count={result['scored_count']}", flush=True)
    week_ends = sorted(
        {
            date.fromisoformat(value) + timedelta(days=4 - date.fromisoformat(value).weekday())
            for value in trading_dates
        }
    )
    weekly: list[dict[str, object]] = []
    for week_end in week_ends:
        if week_end >= today:
            continue
        result = _run(
            services,
            "research.rank-strategy1-week",
            {"week_end": week_end.isoformat()},
            f"recent-backfill:strategy1-week:{week_end}",
        )
        if result is None:
            raise RuntimeError(f"weekly ranking failed for {week_end}")
        weekly.append(result)
        response = app.test_client().get(
            f"/api/v2/research/rankings?week_end={week_end.isoformat()}&limit=20"
        )
        if response.status_code != 200 or not response.json["members"]:
            raise RuntimeError(f"ranking API readback failed for {week_end}")
        print(f"ranked_week={week_end} count={result['ranked_count']}", flush=True)
    print(
        f"backfill_complete imported={imported} refreshed={refreshed} "
        f"failed={len(failures)} daily={len(daily)} weekly={len(weekly)}",
        flush=True,
    )
    if failures:
        print("failed_symbols=" + ",".join(failures[:50]), flush=True)
    return 0 if not failures else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - do not print provider or token details
        print(f"Recent research backfill failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
