"""Refresh NSE index and BSE equity/index identities from Kite and local CSVs."""

from datetime import UTC, datetime

from run import create_app


def main() -> int:
    app = create_app()
    services = app.extensions["screener_services"]
    today = datetime.now(UTC).date()
    for kind, exchange in (
        ("reference.sync-kite-instruments", "NSE"),
        ("reference.sync-bse-instruments", "BSE"),
    ):
        job = services.jobs.submit(f"reference-v4-index-bse:{exchange}:{today}", kind, {})
        if job.result is not None:
            result = job.result
        else:
            completed = services.worker.run_once()
            if completed is None or completed.job_id != job.job_id or completed.result is None:
                raise RuntimeError(f"{exchange} reference sync failed")
            result = completed.result
        print(f"reference_sync={exchange} matched={result['matched_count']}", flush=True)
    for symbol, exchange in (
        ("NIFTY 50", "NSE"),
        ("NIFTY 100", "NSE"),
        ("NIFTY BANK", "NSE"),
        ("NIFTY 500", "NSE"),
        ("SENSEX", "BSE"),
    ):
        instrument = services.market.instrument(symbol, exchange)
        if not str(instrument["isin"]).startswith("INDEX:"):
            raise RuntimeError(f"index identity is invalid: {exchange}:{symbol}")
        response = app.test_client().get(
            f"/api/v2/reference/instruments?symbol={symbol.replace(' ', '%20')}"
        )
        if response.status_code != 200 or not response.json["instruments"]:
            raise RuntimeError("index reference API readback failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
