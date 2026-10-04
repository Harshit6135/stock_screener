from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from flask import Flask

from src.domains.market_data import NormalizedBar
from src.domains.reference_data import TrackedInstrument
from src.gates.composition import ApplicationServices
from src.gates.http.actions import create_actions_blueprint
from src.platform_kernel import Money
from src.platform_kernel.sqlite import sqlite_connection


def _services(tmp_path):
    services = ApplicationServices.create(tmp_path)
    source = (Path(__file__).resolve().parents[3] / "strategies" / "momentum.yml").read_text()
    source = (
        source.replace("version: 1.2.0", "version: 1.2.1")
        .replace("max_positions: 15", "max_positions: 1")
        .replace("exit_threshold: 40", "exit_threshold: 41")
    )
    revision = services.strategies.create_from_yaml(source)
    services.strategies.activate(str(revision["revision_id"]))
    instrument_id = str(uuid4())
    services.market.upsert_instruments(
        [TrackedInstrument(instrument_id, "INE000000001", "ABC", "NSE", "42", date(2026, 9, 4))]
    )
    services.market.create_universe_snapshot(
        snapshot_id="action-current-universe",
        index_name="NIFTY 500",
        snapshot_date=date(2026, 9, 4),
        source_url="fixture://nse",
        raw_csv=b"ABC",
        members=[
            {
                "isin": "INE000000001",
                "symbol": "ABC",
                "company_name": "ABC",
                "industry": "IT",
                "series": "EQ",
            }
        ],
    )
    services.market.upsert_bars(
        instrument_id,
        [NormalizedBar(instrument_id, date(2026, 9, 7), 100, 105, 95, 102, 1000)],
        "bar-abc-20260907",
    )
    ranking = services.publisher.publish_json(
        "rankings/momentum", str(uuid4()), {"week_end": "2026-09-04"}
    )
    services.market.upsert_indicators(
        services.research._indicator_set("momentum", None),
        date(2026, 9, 4),
        {instrument_id: {"atrr_14": 5, "close": 100}},
        "bar-abc-20260904",
    )
    with sqlite_connection(services.database) as connection:
        connection.execute(
            """INSERT INTO research_weekly_rankings
               (strategy_id, strategy_revision_id, week_end, instrument_id, symbol, score, rank, artifact_id)
               VALUES ('momentum', ?, '2026-09-04', ?, 'ABC', 80, 1, ?)""",
            (
                services.strategy_runtime.revision("momentum")["revision_id"],
                instrument_id,
                ranking.artifact_id,
            ),
        )
    return services, instrument_id


def _payload(account_id="paper"):
    return {
        "account_id": account_id,
        "strategy_id": "momentum",
        "action_date": "2026-09-07",
        "max_positions": 1,
    }


def test_generated_strategy_proposal_cannot_create_synthetic_portfolio_fill(tmp_path):
    services, _ = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    job = services.jobs.submit(
        "portfolio-action-20260907", "actions.generate-portfolio-proposal", _payload()
    )
    completed = services.worker.run_once()
    assert completed.job_id == job.job_id
    assert completed.status.value == "SUCCEEDED"
    proposal = services.actions.proposals("paper")[0]
    assert proposal["status"] == "PENDING"
    assert proposal["decisions"][0]["type"] == "BUY"
    app = Flask(__name__)
    app.register_blueprint(create_actions_blueprint(services.actions))
    client = app.test_client()
    path = f"/api/actions/proposals/{proposal['proposal_id']}"
    assert client.get(path).status_code == 200
    assert client.post(f"{path}/process").status_code == 409
    assert client.post(f"{path}/approve").json["status"] == "APPROVED"
    blocked = client.post(f"{path}/process")
    assert blocked.status_code == 409
    assert "confirmed Kite or manual execution" in blocked.json["error"]
    assert services.ledger.accounts()[0]["version"] == 0
    projection = services.ledger.projection("paper")
    assert projection.open_lots == ()
    assert projection.cash.amount == Decimal(1000)
    assert [event["event_type"] for event in services.actions.events(proposal["proposal_id"])] == [
        "GENERATED",
        "APPROVED",
    ]


def test_execution_policy_parity_is_protected_immutable_and_readable(tmp_path):
    services, _ = _services(tmp_path)
    baseline = {
        "signal_timing": "close",
        "execution_timing": "next_tradable_open",
        "sell_before_buy": True,
        "cash_resize": "actual_open_with_available_cash",
        "zero_unit_buy": "remain_pending",
        "vacancy_advance": "opt_in",
        "stale_buy_threshold": "0.05",
        "pyramid_enabled": "explicit_operator_switch",
        "pyramid_fraction": "0.5",
    }
    app = Flask(__name__)
    app.register_blueprint(create_actions_blueprint(services.actions))
    client = app.test_client()
    endpoint = "/api/actions/execution-policy-parity"
    assert client.post(endpoint, json={"v3_policy": baseline}).status_code == 201
    response = client.post(endpoint, json={"v3_policy": baseline})
    assert response.status_code == 201
    artifact_id = response.json["parity_artifact_id"]
    assert response.json["parity"] is True
    readback = client.get(f"{endpoint}/{artifact_id}")
    assert readback.status_code == 200
    assert readback.json["data"]["execution_policy_version"] == "v4-portfolio-execution-1"
