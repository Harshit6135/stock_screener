"""Replay the completed week from persisted rankings and later Kite bars."""

from run import create_app


def main() -> int:
    app = create_app()
    services = app.extensions["screener_services"]
    for strategy_id in ("strategy1", "strategy2"):
        job = services.jobs.submit(
            f"backtest-v4-review2:{strategy_id}:2026-09-07:2026-09-11:cash1000000:max5",
            "backtest.run",
            {
                "strategy_id": strategy_id,
                "start_date": "2026-09-07",
                "end_date": "2026-09-11",
                "starting_cash": "1000000",
                "max_positions": 5,
            },
            max_attempts=1,
        )
        if job.result is not None:
            result = job.result
        else:
            completed = services.worker.run_once()
            if completed is None or completed.job_id != job.job_id or completed.result is None:
                raise RuntimeError(f"{strategy_id} replay job failed")
            result = completed.result
        response = app.test_client().get(f"/api/v2/backtests/runs/{result['run_id']}")
        if (
            response.status_code != 200
            or response.json["artifact"]["quality"] != "PARTIAL"
            or result["session_count"] != 5
            or result["fill_count"] < 1
        ):
            raise RuntimeError(f"{strategy_id} replay readback failed")
        print(
            f"backtest_verified={strategy_id} sessions={result['session_count']} "
            f"fills={result['fill_count']} total_return={result['metrics']['total_return']}",
            flush=True,
        )
    if len(app.test_client().get("/api/v2/backtests/runs?limit=2").json["runs"]) != 2:
        raise RuntimeError("backtest run listing failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
