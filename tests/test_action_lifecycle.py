"""Action generation, review, processing and retry against durable stores."""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from flask import Flask

from src.application.actions_web import create_actions_blueprint
from src.application.composition import ApplicationServices
from src.application.market_repository import TrackedInstrument
from src.application.sqlite import sqlite_connection
from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.portfolio_accounting import Fill, FillSide


def _services(tmp_path):
    services = ApplicationServices.create(tmp_path)
    instrument_id = str(uuid4())
    services.market.upsert_instruments(
        [TrackedInstrument(instrument_id, "INE000000001", "ABC", "NSE", "42", date(2026, 9, 4))]
    )
    services.market.upsert_bars(
        instrument_id,
        [NormalizedBar(instrument_id, date(2026, 9, 7), 100, 105, 95, 102, 1000)],
        "bar-abc-20260907",
    )
    ranking = services.publisher.publish_json(
        "rankings/strategy1", str(uuid4()), {"week_end": "2026-09-04"}
    )
    with sqlite_connection(services.database) as connection:
        connection.execute(
            """INSERT INTO research_weekly_rankings
               (strategy_id, week_end, instrument_id, symbol, score, rank, artifact_id)
               VALUES ('strategy1', '2026-09-04', ?, 'ABC', 80, 1, ?)""",
            (instrument_id, ranking.artifact_id),
        )
    return services, instrument_id


def _payload(account_id="paper"):
    return {
        "account_id": account_id,
        "strategy_id": "strategy1",
        "action_date": "2026-09-07",
        "max_positions": 1,
    }


def test_generate_approve_process_and_idempotent_retry(tmp_path):
    services, instrument_id = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    job = services.jobs.submit(
        "paper-action-20260907", "actions.generate-paper-proposal", _payload()
    )
    completed = services.worker.run_once()
    assert completed.job_id == job.job_id
    assert completed.status.value == "SUCCEEDED"
    proposal = services.actions.proposals("paper")[0]
    assert proposal["status"] == "PENDING"
    assert proposal["decisions"][0]["type"] == "BUY"
    app = Flask(__name__)
    app.config["OPERATOR_TOKEN"] = "test-secret"
    app.register_blueprint(create_actions_blueprint(services.actions))
    client = app.test_client()
    path = f"/api/v2/actions/proposals/{proposal['proposal_id']}"
    assert client.get(path).status_code == 401
    headers = {"X-Operator-Token": "test-secret"}
    assert client.get(path, headers=headers).status_code == 200
    assert client.post(f"{path}/process", headers=headers).status_code == 409
    assert client.post(f"{path}/approve", headers=headers).json["status"] == "APPROVED"
    assert client.post(f"{path}/process", headers=headers).json["status"] == "PROCESSED"
    assert client.post(f"{path}/process", headers=headers).json["status"] == "PROCESSED"
    assert services.ledger.accounts()[0]["version"] == 1
    projection = services.ledger.projection("paper")
    assert projection.open_lots[0].instrument_id == instrument_id
    assert projection.cash.amount == Decimal(0)
    assert [event["event_type"] for event in services.actions.events(proposal["proposal_id"])] == [
        "GENERATED",
        "APPROVED",
        "PROCESSED",
    ]


def test_multiple_fifo_lots_and_stale_proposal(tmp_path):
    services, instrument_id = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    for version, price in enumerate((Decimal(90), Decimal(110))):
        services.ledger.record_fills(
            "paper",
            f"manual-{version}",
            version,
            [
                Fill(
                    instrument_id,
                    date(2026, 9, 4),
                    FillSide.BUY,
                    Quantity(1),
                    Money(price),
                    Money(0),
                    datetime.fromisoformat("2026-09-04T09:15:00+05:30"),
                )
            ],
        )
    proposal = services.actions.generate(_payload())
    assert proposal["status"] == "PENDING"
    assert services.actions.generate(_payload())["proposal_id"] == proposal["proposal_id"]
    services.actions.decide(proposal["proposal_id"], "APPROVED")
    services.ledger.record_fills(
        "paper",
        "intervening",
        2,
        [
            Fill(
                instrument_id,
                date(2026, 9, 7),
                FillSide.SELL,
                Quantity(1),
                Money(100),
                Money(0),
                datetime.fromisoformat("2026-09-07T09:15:00+05:30"),
            )
        ],
    )
    with pytest.raises(DomainValidationError, match="stale ledger version"):
        services.actions.process(proposal["proposal_id"])
    assert services.actions.proposal(proposal["proposal_id"])["status"] == "APPROVED"


def test_recovers_projection_after_published_artifact(tmp_path):
    services, _ = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    original = services.actions.generate(_payload())
    with sqlite_connection(services.database) as connection:
        connection.execute(
            "DELETE FROM action_proposal_events WHERE proposal_id=?", (original["proposal_id"],)
        )
        connection.execute(
            "DELETE FROM action_proposals WHERE proposal_id=?", (original["proposal_id"],)
        )
    restored = services.actions.generate(_payload())
    assert restored["proposal_id"] == original["proposal_id"]
    assert [item["event_type"] for item in services.actions.events(restored["proposal_id"])] == [
        "GENERATED"
    ]


def test_invalidated_proposal_cannot_process(tmp_path):
    services, _ = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    proposal = services.actions.generate(_payload())
    services.actions.decide(proposal["proposal_id"], "APPROVED")
    services.catalog.set_status(proposal["artifact_id"], "QUALIFIED", "upstream revised")
    with pytest.raises(DomainValidationError, match="artifact is not valid"):
        services.actions.process(proposal["proposal_id"])
    assert services.ledger.accounts()[0]["version"] == 0


def test_action_generation_uses_active_configuration(tmp_path):
    services, _ = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    config = services.configs.create(
        "strategy1",
        {
            "initial_capital": "100000",
            "risk_threshold": "1",
            "max_positions": 1,
            "min_position_percent": "0.05",
            "exit_threshold": "41",
            "buffer_percent": "0.30",
            "sl_multiplier": "2",
            "hard_sl_percent": "0.03",
            "atr_fallback_percent": "0.06",
            "max_concentration_pct": "0.25",
        },
    )
    services.configs.approve(config["revision_id"], "2026-09-01")
    payload = _payload()
    del payload["max_positions"]
    proposal = services.actions.generate(payload)
    _, artifact = services.artifacts.read_json("actions/proposals", proposal["proposal_id"])
    assert artifact["config_revision_id"] == config["revision_id"]
    assert artifact["policy"]["exit_score"] == "41"
    conflicting = _payload()
    conflicting["max_positions"] = 2
    with pytest.raises(DomainValidationError, match="conflicts"):
        services.actions.generate(conflicting)
    result = services.backtests.execute(
        {"strategy_id": "strategy1", "start_date": "2026-09-07", "end_date": "2026-09-07"}
    )
    _, report = services.artifacts.read_json("runs/backtests", result["artifact_id"])
    assert report["manifest"]["parameters"]["config_revision_id"] == config["revision_id"]
