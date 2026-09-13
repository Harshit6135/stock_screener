"""Exercise 10 completed sessions from Kite/v3 OHLCV through v4 weekly rankings."""

import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory


def _run(services, kind: str, payload: dict[str, object], fingerprint: str) -> dict[str, object]:
    services.jobs.submit(fingerprint, kind, payload, max_attempts=1)
    result = services.worker.run_once()
    if result is None or result.result is None:
        print(
            f"job_failed kind={kind} status={result.status.value if result else 'idle'} "
            f"error_class={result.last_error if result else 'none'}",
            file=sys.stderr,
        )
        raise RuntimeError("research job failed")
    return result.result


def main() -> int:
    try:
        with TemporaryDirectory(prefix="screener-research-live-") as temporary_directory:
            os.environ["SCREENER_DATA_DIRECTORY"] = temporary_directory
            from run import create_app

            class SmokeConfig:
                TESTING = True
                SECRET_KEY = "smoke-only"
                DATA_DIRECTORY = Path(temporary_directory)
                OPERATOR_TOKEN = "smoke-only"

            app = create_app(SmokeConfig)
            services = app.extensions["screener_services"]
            synced = _run(services, "reference.sync-kite-instruments", {}, "research-live:sync")
            end = datetime.now(UTC).date()
            symbols = ("RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK")
            for symbol in symbols:
                _run(
                    services,
                    "market.import-v3-bars",
                    {"symbol": symbol, "start_date": "2025-07-18", "end_date": "2026-07-17"},
                    f"research-live:v3:{symbol}",
                )
                _run(
                    services,
                    "market.fetch-kite-bars",
                    {"symbol": symbol, "start_date": "2026-07-18", "end_date": end.isoformat()},
                    f"research-live:kite:{symbol}",
                )
            end_dates = [
                item["as_of_date"]
                for item in services.market.bars(
                    str(services.market.instrument("RELIANCE")["instrument_id"]),
                    end - timedelta(days=25),
                    end,
                )
            ][-10:]
            if len(end_dates) != 10:
                raise RuntimeError("fewer than 10 completed Kite sessions were ingested")
            daily_results = [
                _run(
                    services,
                    "research.calculate-strategy1-day",
                    {"as_of_date": trading_date},
                    f"research-live:strategy1:{trading_date}",
                )
                for trading_date in end_dates
            ]
            week_ends = sorted(
                {
                    date.fromisoformat(value)
                    + timedelta(days=4 - date.fromisoformat(value).weekday())
                    for value in end_dates
                }
            )
            weekly_results = [
                _run(
                    services,
                    "research.rank-strategy1-week",
                    {"week_end": week_end.isoformat()},
                    f"research-live:week:{week_end.isoformat()}",
                )
                for week_end in week_ends
                if week_end < end
            ]
            client = app.test_client()
            latest = daily_results[-1]
            for category, key in (
                ("features", "feature_artifact_id"),
                ("percentiles", "percentile_artifact_id"),
                ("scores", "score_artifact_id"),
            ):
                response = client.get(f"/api/v2/research/{category}/{latest[key]}")
                if response.status_code != 200:
                    raise RuntimeError(f"{category} artifact was not readable through v4 API")
            for week in weekly_results:
                artifact = client.get(f"/api/v2/research/rankings/{week['artifact_id']}")
                top = client.get(f"/api/v2/research/rankings?week_end={week['week_end']}")
                if artifact.status_code != 200 or top.status_code != 200 or not top.json["members"]:
                    raise RuntimeError("weekly ranking was not readable through v4 API")
            print(
                "Research live smoke passed: "
                f"tracked={synced['matched_count']}, symbols={len(symbols)}, "
                f"daily_sessions={len(daily_results)}, weeks={len(weekly_results)}, "
                f"latest_scored={latest['scored_count']}, latest={end_dates[-1]}."
            )
            return 0
    except Exception as exc:  # noqa: BLE001 - never print credential-bearing provider details
        print(f"Research live smoke failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
