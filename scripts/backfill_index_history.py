"""Fetch dated Kite histories for the v3 ticker indices and other tracked indices."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from run import create_app
from src.platform_kernel import DomainValidationError

INDICES = (
    ("NSE", "NIFTY 50"),
    ("NSE", "NIFTY 100"),
    ("NSE", "NIFTY BANK"),
    ("NSE", "NIFTY MIDCAP 50"),
    ("NSE", "INDIA VIX"),
    ("BSE", "SENSEX"),
    ("BSE", "BANKEX"),
)


def main() -> int:
    app = create_app()
    services = app.extensions["screener_services"]
    client = app.test_client()
    today = datetime.now(UTC).date().isoformat()
    failures = []
    for exchange, symbol in INDICES:
        try:
            services.market.instrument(symbol, exchange)
        except DomainValidationError:
            failures.append(f"{exchange}:{symbol}:identity")
            continue
        for start_date, end_date in (("2025-07-18", "2026-07-17"), ("2026-07-18", today)):
            fingerprint = f"index-history:{exchange}:{symbol}:{start_date}:{end_date}"
            job = services.jobs.submit(
                fingerprint,
                "market.fetch-kite-bars",
                {
                    "exchange": exchange,
                    "symbol": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                max_attempts=1,
            )
            if job.result is not None:
                result = job.result
            elif job.status.value == "QUEUED":
                completed = services.worker.run_once()
                result = completed.result if completed and completed.job_id == job.job_id else None
            else:
                result = None
            if result is None:
                failures.append(f"{exchange}:{symbol}:{start_date}")
                break
            print(
                f"index_history={exchange}:{symbol} start={start_date} bars={result['bar_count']}",
                flush=True,
            )
            time.sleep(0.5)
        response = client.get(
            f"/api/v2/market/bars/{symbol}?exchange={exchange}&start=2026-08-31&end=2026-09-11"
        )
        if response.status_code != 200 or len(response.json["bars"]) != 10:
            failures.append(f"{exchange}:{symbol}:readback")
    if failures:
        print(f"index_history_failures={','.join(failures)}", flush=True)
        return 2
    print(f"index_histories_verified={len(INDICES)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
