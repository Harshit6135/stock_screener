"""Fetch NIFTY 500 benchmark history through the durable Kite market job."""

from __future__ import annotations

from datetime import UTC, datetime

from run import create_app


def main() -> int:
    app = create_app()
    services = app.extensions["screener_services"]
    today = datetime.now(UTC).date()
    instrument = services.market.instrument("NIFTY 500")
    if instrument["isin"] != "INDEX:NIFTY 500":
        raise RuntimeError("NIFTY 500 does not have the expected index identity")
    for start_date, end_date in (
        ("2025-07-18", "2026-07-17"),
        ("2026-07-18", today.isoformat()),
    ):
        fingerprint = f"benchmark:nifty500:{start_date}:{end_date}"
        job = services.jobs.submit(
            fingerprint,
            "market.fetch-kite-bars",
            {"symbol": "NIFTY 500", "start_date": start_date, "end_date": end_date},
            max_attempts=1,
        )
        result = job.result if job.result is not None else services.worker.run_once().result
        if result is None:
            raise RuntimeError(f"benchmark fetch failed for {start_date} to {end_date}")
        print(
            f"benchmark_chunk={start_date}:{end_date} "
            f"bars={result['bar_count']} artifact={result['artifact_id']}",
            flush=True,
        )
    response = app.test_client().get(
        "/api/v2/market/bars/NIFTY 500?start=2026-08-31&end=2026-09-11"
    )
    if response.status_code != 200 or len(response.json["bars"]) != 10:
        raise RuntimeError("NIFTY 500 history API readback failed")
    print("benchmark_history_verified=10_sessions", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
