"""Read-only Kite instrument and OHLCV ingestion through the v4 job/API path."""

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    try:
        with TemporaryDirectory(prefix="screener-market-live-") as temporary_directory:
            os.environ["SCREENER_DATA_DIRECTORY"] = temporary_directory
            from run import create_app

            class SmokeConfig:
                TESTING = True
                SECRET_KEY = "smoke-only"
                DATA_DIRECTORY = Path(temporary_directory)

            app = create_app(SmokeConfig)
            services = app.extensions["screener_services"]
            services.jobs.submit(
                "market-live:sync", "reference.sync-kite-instruments", {}, max_attempts=1
            )
            completed = services.worker.run_once()
            if completed is None or completed.result is None:
                print(
                    f"sync_job_status={completed.status.value if completed else 'idle'} "
                    f"error_class={completed.last_error if completed else 'none'}",
                    file=sys.stderr,
                )
                raise RuntimeError(
                    f"instrument sync failed: {completed.status if completed else 'idle'}"
                )
            matched_count = completed.result["matched_count"]
            services.jobs.submit(
                "market-live:v3-reliance",
                "market.import-v3-bars",
                {
                    "symbol": "RELIANCE",
                    "start_date": "2025-07-18",
                    "end_date": "2026-07-17",
                },
                max_attempts=1,
            )
            completed = services.worker.run_once()
            if completed is None or completed.result is None:
                print(
                    f"import_job_status={completed.status.value if completed else 'idle'} "
                    f"error_class={completed.last_error if completed else 'none'}",
                    file=sys.stderr,
                )
                raise RuntimeError("v3 OHLCV import failed")
            imported_count = completed.result["bar_count"]
            end = datetime.now(UTC).date()
            start = date.fromisoformat("2026-07-18")
            services.jobs.submit(
                "market-live:reliance",
                "market.fetch-kite-bars",
                {
                    "symbol": "RELIANCE",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                },
                max_attempts=1,
            )
            completed = services.worker.run_once()
            if completed is None or completed.result is None:
                print(
                    f"bars_job_status={completed.status.value if completed else 'idle'} "
                    f"error_class={completed.last_error if completed else 'none'}",
                    file=sys.stderr,
                )
                raise RuntimeError(
                    f"market fetch failed: {completed.status if completed else 'idle'}"
                )
            client = app.test_client()
            instruments = client.get("/api/v2/reference/instruments?symbol=RELIANCE")
            history = client.get(
                f"/api/v2/market/bars/RELIANCE?start={start.isoformat()}&end={end.isoformat()}"
            )
            if instruments.status_code != 200 or len(instruments.json["instruments"]) != 1:
                raise RuntimeError("instrument was not readable through v4 API")
            if history.status_code != 200 or len(history.json["bars"]) < 10:
                raise RuntimeError("market bars were not readable through v4 API")
            print(
                "Market live smoke passed: "
                f"matched instruments={matched_count}, "
                f"v3 bars={imported_count}, Kite bars={len(history.json['bars'])}, "
                f"last={history.json['bars'][-1]['as_of_date']}."
            )
            return 0
    except Exception as exc:  # noqa: BLE001 - never expose provider or credential details
        print(f"Market live smoke failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
