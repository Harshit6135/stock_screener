"""Read back the persisted ten-session market-to-ranking path through HTTP."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from run import create_app
from src.application.sqlite import sqlite_connection


def main() -> int:
    app = create_app()
    services = app.extensions["screener_services"]
    client = app.test_client()
    for path in ("/health/live", "/health/ready", "/integrations/kite"):
        response = client.get(path)
        if response.status_code != 200:
            raise RuntimeError(f"endpoint failed: {path} ({response.status_code})")
    instruments = client.get("/api/v2/reference/instruments?symbol=RELIANCE")
    if instruments.status_code != 200 or len(instruments.json["instruments"]) != 1:
        raise RuntimeError("reference instrument readback failed")
    bars = client.get("/api/v2/market/bars/RELIANCE?start=2026-08-31&end=2026-09-11")
    if bars.status_code != 200 or len(bars.json["bars"]) != 10:
        raise RuntimeError("market bar readback failed")
    benchmark = client.get("/api/v2/market/bars/NIFTY 500?start=2026-08-31&end=2026-09-11")
    if benchmark.status_code != 200 or len(benchmark.json["bars"]) != 10:
        raise RuntimeError("NIFTY 500 benchmark readback failed")
    with sqlite_connection(services.database, read_only=True, row_factory=True) as connection:
        rows = connection.execute(
            """SELECT fingerprint, result_json FROM ops_jobs
               WHERE fingerprint LIKE 'recent-backfill:strategy1-v4-port-2:%'
               ORDER BY fingerprint"""
        ).fetchall()
        if len(rows) != 10:
            raise RuntimeError(f"expected ten corrected daily jobs, found {len(rows)}")
        for row in rows:
            result = json.loads(row["result_json"])
            for kind, key in (
                ("features", "feature_artifact_id"),
                ("percentiles", "percentile_artifact_id"),
                ("scores", "score_artifact_id"),
            ):
                artifact_id = result[key]
                response = client.get(f"/api/v2/research/{kind}/{artifact_id}")
                if response.status_code != 200:
                    raise RuntimeError(f"{kind} artifact readback failed")
                status = connection.execute(
                    "SELECT status FROM catalog_artifacts WHERE artifact_id=?", (artifact_id,)
                ).fetchone()
                if status is None or status["status"] != "VALID":
                    raise RuntimeError(f"corrected {kind} artifact is not valid")
        for week_end in ("2026-09-04", "2026-09-11"):
            response = client.get(f"/api/v2/research/rankings?week_end={week_end}&limit=20")
            if response.status_code != 200 or len(response.json["members"]) != 20:
                raise RuntimeError("ranking query readback failed")
            result_row = connection.execute(
                "SELECT result_json FROM ops_jobs WHERE fingerprint=?",
                (f"recent-backfill:strategy1-v4-port-2-week:{week_end}",),
            ).fetchone()
            if result_row is None:
                raise RuntimeError("corrected ranking job is missing")
            ranking_id = json.loads(result_row["result_json"])["artifact_id"]
            artifact_response = client.get(f"/api/v2/research/rankings/{ranking_id}")
            if artifact_response.status_code != 200:
                raise RuntimeError("ranking artifact readback failed")
            status = connection.execute(
                "SELECT status FROM catalog_artifacts WHERE artifact_id=?", (ranking_id,)
            ).fetchone()
            if status is None or status["status"] != "VALID":
                raise RuntimeError("corrected ranking artifact is not valid")
        strategy2_rows = connection.execute(
            """SELECT fingerprint, result_json FROM ops_jobs
               WHERE fingerprint LIKE 'recent-backfill:strategy2-v4-port-1:%'
               ORDER BY fingerprint"""
        ).fetchall()
        if len(strategy2_rows) != 10:
            raise RuntimeError("expected ten Strategy 2 daily jobs")
        for row in strategy2_rows:
            result = json.loads(row["result_json"])
            for kind, key in (
                ("features", "feature_artifact_id"),
                ("percentiles", "percentile_artifact_id"),
                ("scores", "score_artifact_id"),
            ):
                artifact_id = result[key]
                response = client.get(
                    f"/api/v2/research/{kind}/{artifact_id}?strategy_id=strategy2"
                )
                if response.status_code != 200:
                    raise RuntimeError(f"Strategy 2 {kind} artifact readback failed")
                status = connection.execute(
                    "SELECT status FROM catalog_artifacts WHERE artifact_id=?", (artifact_id,)
                ).fetchone()
                if status is None or status["status"] != "VALID":
                    raise RuntimeError(f"Strategy 2 {kind} artifact is not valid")
        for week_end in ("2026-09-04", "2026-09-11"):
            response = client.get(
                f"/api/v2/research/rankings?week_end={week_end}&strategy_id=strategy2&limit=20"
            )
            if response.status_code != 200 or len(response.json["members"]) != 20:
                raise RuntimeError("Strategy 2 weekly ranking readback failed")
            result_row = connection.execute(
                "SELECT result_json FROM ops_jobs WHERE fingerprint=?",
                (f"recent-backfill:strategy2-v4-port-1-week:{week_end}",),
            ).fetchone()
            if result_row is None:
                raise RuntimeError("Strategy 2 ranking job is missing")
            ranking_id = json.loads(result_row["result_json"])["artifact_id"]
            artifact_response = client.get(f"/api/v2/research/rankings/{ranking_id}")
            if artifact_response.status_code != 200:
                raise RuntimeError("Strategy 2 ranking artifact readback failed")
            status = connection.execute(
                "SELECT status FROM catalog_artifacts WHERE artifact_id=?", (ranking_id,)
            ).fetchone()
            if status is None or status["status"] != "VALID":
                raise RuntimeError("Strategy 2 ranking artifact is not valid")
    print(
        "verified_live_path="
        f"{datetime.now(UTC).date()} reference=1 market_sessions=10 "
        "daily_feature_percentile_score=10_each_strategy weekly_rankings=2_each_strategy"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
