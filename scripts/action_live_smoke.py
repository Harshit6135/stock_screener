"""Replay stored rankings and bars through an isolated proposal lifecycle."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

from src.application.actions_web import create_actions_blueprint
from src.application.composition import ApplicationServices
from src.application.market_repository import TrackedInstrument
from src.application.sqlite import sqlite_connection
from src.market_data import NormalizedBar
from src.platform_kernel import Money


def main() -> None:
    source = Path("instance/system.db").resolve()
    with sqlite_connection(source, read_only=True, row_factory=True) as connection:
        rankings = connection.execute(
            """SELECT r.instrument_id, r.symbol, r.score, i.isin, i.exchange,
                      i.provider_token, i.observed_on, b.open, b.high, b.low,
                      b.close, b.volume
               FROM research_weekly_rankings r
               JOIN reference_instruments i ON i.instrument_id=r.instrument_id
               JOIN market_bars b ON b.instrument_id=r.instrument_id
               WHERE r.strategy_id='strategy1' AND r.week_end='2026-09-04'
                 AND b.as_of_date='2026-09-07'
               ORDER BY r.rank LIMIT 3"""
        ).fetchall()
    if len(rankings) != 3:
        raise RuntimeError("three stored top-ranked stocks with bars are required")
    with TemporaryDirectory(prefix="screener-action-smoke-") as temporary:
        services = ApplicationServices.create(temporary)
        ranking_artifact = services.publisher.publish_json(
            "smoke/source-rankings",
            "source-strategy1-2026-09-04",
            {"source_database": str(source), "rows": [dict(row) for row in rankings]},
        )
        for rank, row in enumerate(rankings, start=1):
            instrument_id = str(row["instrument_id"])
            services.market.upsert_instruments(
                [
                    TrackedInstrument(
                        instrument_id,
                        str(row["isin"]),
                        str(row["symbol"]),
                        str(row["exchange"]),
                        str(row["provider_token"]),
                        date.fromisoformat(str(row["observed_on"])),
                    )
                ]
            )
            services.market.upsert_bars(
                instrument_id,
                [
                    NormalizedBar(
                        instrument_id,
                        date(2026, 9, 7),
                        Decimal(str(row["open"])),
                        Decimal(str(row["high"])),
                        Decimal(str(row["low"])),
                        Decimal(str(row["close"])),
                        int(row["volume"]),
                    )
                ],
                ranking_artifact.artifact_id,
            )
            with sqlite_connection(services.database) as connection:
                connection.execute(
                    """INSERT INTO research_weekly_rankings
                       (strategy_id, week_end, instrument_id, symbol, score, rank, artifact_id)
                       VALUES ('strategy1', '2026-09-04', ?, ?, ?, ?, ?)""",
                    (
                        instrument_id,
                        row["symbol"],
                        row["score"],
                        rank,
                        ranking_artifact.artifact_id,
                    ),
                )
        services.ledger.open_account("portfolio", Money(100000))
        job = services.jobs.submit(
            "smoke-action-strategy1-20260907",
            "actions.generate-portfolio-proposal",
            {
                "account_id": "portfolio",
                "strategy_id": "strategy1",
                "action_date": "2026-09-07",
                "max_positions": 3,
            },
        )
        completed = services.worker.run_once()
        if (
            completed is None
            or completed.job_id != job.job_id
            or completed.status.value != "SUCCEEDED"
        ):
            raise RuntimeError(f"proposal job failed: {completed}")
        proposal = services.actions.proposals("portfolio")[0]
        app = Flask(__name__)
        app.register_blueprint(create_actions_blueprint(services.actions))
        client = app.test_client()
        path = f"/api/v2/actions/proposals/{proposal['proposal_id']}"
        approved = client.post(f"{path}/approve")
        processed = client.post(f"{path}/process")
        if approved.status_code != 200 or processed.status_code != 409:
            raise RuntimeError(f"review/process failed: {approved.json}, {processed.json}")
        result = {
            "job_status": completed.status.value,
            "proposal_status": services.actions.proposal(proposal["proposal_id"])["status"],
            "processing_blocked": processed.json["error"],
            "decision_types": [item["type"] for item in proposal["decisions"]],
            "event_types": [
                item["event_type"] for item in services.actions.events(proposal["proposal_id"])
            ],
            "ledger_version": services.ledger.accounts()[0]["version"],
            "open_lots": len(services.ledger.projection("portfolio").open_lots),
            "cash": str(services.ledger.projection("portfolio").cash.amount),
        }
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
