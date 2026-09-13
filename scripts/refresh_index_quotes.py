"""Refresh and read back freshness-labelled Kite index quotes."""

from datetime import UTC, datetime

from run import create_app


def main() -> int:
    app = create_app()
    services = app.extensions["screener_services"]
    fingerprint = f"index-quotes:{datetime.now(UTC):%Y%m%dT%H%M%S}"
    job = services.jobs.submit(fingerprint, "market.fetch-kite-index-quotes", {}, max_attempts=1)
    completed = services.worker.run_once()
    if completed is None or completed.job_id != job.job_id or completed.result is None:
        raise RuntimeError("Kite index quote refresh failed")
    response = app.test_client().get("/api/v2/market/indices/quotes")
    if response.status_code != 200 or len(response.json["quotes"]) < 5:
        raise RuntimeError("index quote API readback failed")
    print(
        f"index_quotes_verified={len(response.json['quotes'])} "
        f"fresh={sum(item['freshness'] == 'FRESH' for item in response.json['quotes'])}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
