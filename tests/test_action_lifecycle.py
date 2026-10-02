"""Action generation, review, processing and retry against durable stores."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
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
    source = (Path(__file__).resolve().parents[1] / "strategies" / "momentum.yml").read_text()
    source = source.replace("version: 1.2.0", "version: 1.2.1").replace(
        "max_positions: 15", "max_positions: 1"
    ).replace("exit_threshold: 40", "exit_threshold: 41")
    revision = services.strategies.create_from_yaml(source)
    services.strategies.activate(str(revision["revision_id"]))
    instrument_id = str(uuid4())
    services.market.upsert_instruments(
        [TrackedInstrument(instrument_id, "INE000000001", "ABC", "NSE", "42", date(2026, 9, 4))]
    )
    services.market.create_universe_snapshot(
        snapshot_id="action-current-universe", index_name="NIFTY 500",
        snapshot_date=date(2026, 9, 4), source_url="fixture://nse",
        raw_csv=b"ABC", members=[{"isin": "INE000000001", "symbol": "ABC",
            "company_name": "ABC", "industry": "IT", "series": "EQ"}],
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
        services.research._indicator_set("momentum", None), date(2026, 9, 4),
        {instrument_id: {"atrr_14": 5, "close": 100}}, "bar-abc-20260904",
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
    path = f"/api/v2/actions/proposals/{proposal['proposal_id']}"
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


def test_manually_confirmed_transaction_processes_once(tmp_path):
    services, instrument_id = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    proposal = services.actions.create_manual(
        {
            "account_id": "paper",
            "action_date": "2026-09-08",
            "entries": [
                {"symbol": "ABC", "exchange": "NSE", "side": "BUY", "units": 2, "price": "100"}
            ],
            "reason": "confirmed contract note",
        }
    )
    services.actions.decide(proposal["proposal_id"], "APPROVED")

    first = services.actions.process(proposal["proposal_id"])
    second = services.actions.process(proposal["proposal_id"])

    assert first["status"] == second["status"] == "PROCESSED"
    assert services.ledger.accounts()[0]["version"] == 1
    projection = services.ledger.projection("paper")
    assert projection.open_lots[0].instrument_id == instrument_id
    assert projection.cash.amount == Decimal(800)


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
    proposal = services.actions.create_manual(
        {
            "account_id": "paper",
            "action_date": "2026-09-08",
            "entries": [
                {"symbol": "ABC", "exchange": "NSE", "side": "SELL", "units": 1, "price": "100"}
            ],
            "reason": "confirmed contract note",
        }
    )
    assert proposal["status"] == "PENDING"
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


def test_recovers_manual_projection_after_published_artifact(tmp_path):
    services, _ = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    payload = {
        "account_id": "paper",
        "action_date": "2026-09-08",
        "entries": [
            {
                "symbol": "ABC",
                "exchange": "NSE",
                "side": "BUY",
                "units": 1,
                "price": "100",
            }
        ],
        "reason": "confirmed contract note",
    }
    original = services.actions.create_manual(payload)
    with sqlite_connection(services.database) as connection:
        connection.execute(
            "DELETE FROM action_proposal_events WHERE proposal_id=?",
            (original["proposal_id"],),
        )
        connection.execute(
            "DELETE FROM action_proposals WHERE proposal_id=?",
            (original["proposal_id"],),
        )

    restored = services.actions.create_manual(payload)

    assert restored["proposal_id"] == original["proposal_id"]
    assert restored["strategy_id"] == "manual"
    assert [item["event_type"] for item in services.actions.events(restored["proposal_id"])] == [
        "GENERATED_MANUAL"
    ]


def test_invalidated_proposal_cannot_process(tmp_path):
    services, _ = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    proposal = services.actions.create_manual(
        {
            "account_id": "paper",
            "action_date": "2026-09-08",
            "entries": [
                {"symbol": "ABC", "exchange": "NSE", "side": "BUY", "units": 1, "price": "100"}
            ],
            "reason": "confirmed contract note",
        }
    )
    services.actions.decide(proposal["proposal_id"], "APPROVED")
    services.catalog.set_status(proposal["artifact_id"], "QUALIFIED", "upstream revised")
    with pytest.raises(DomainValidationError, match="artifact is not valid"):
        services.actions.process(proposal["proposal_id"])
    assert services.ledger.accounts()[0]["version"] == 0


def test_action_generation_uses_active_configuration(tmp_path):
    services, _ = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    source = (Path(__file__).resolve().parents[1] / "strategies" / "momentum.yml").read_text()
    source = source.replace("version: 1.2.0", "version: 1.2.1").replace(
        "max_positions: 15", "max_positions: 1"
    ).replace("exit_threshold: 40", "exit_threshold: 41")
    revision = services.strategies.create_from_yaml(source)
    services.strategies.activate(str(revision["revision_id"]))
    payload = _payload()
    del payload["max_positions"]
    proposal = services.actions.generate(payload)
    _, artifact = services.artifacts.read_json("actions/proposals", proposal["proposal_id"])
    assert artifact["strategy_revision_id"] == revision["revision_id"]
    assert artifact["policy"]["exit_score"] == "41"
    conflicting = _payload()
    conflicting["max_positions"] = 2
    with pytest.raises(DomainValidationError, match="conflicts"):
        services.actions.generate(conflicting)
    result = services.backtests.execute(
        {"strategy_id": "momentum", "start_date": "2026-09-07", "end_date": "2026-09-07"}
    )
    _, report = services.artifacts.read_json("runs/backtests", result["artifact_id"])
    assert report["manifest"]["parameters"]["strategy_revision_id"] == revision["revision_id"]


def test_action_generation_applies_point_in_time_fundamental_filter(tmp_path):
    services, _ = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    fundamentals = services.publisher.publish_json(
        "reference/fundamentals", "fundamentals-action-1",
        {"as_of_date": "2026-09-01", "values": {"missing-is-not-used": {"eps": "1", "debt_equity": "2"}}},
    )
    proposal = services.actions.generate({**_payload(), "fundamentals_artifact_id": fundamentals.artifact_id, "min_eps": "5"})
    assert proposal["decisions"][0]["type"] == "NO_ACTION"


def test_action_policy_records_explicit_pyramid_switch_and_execution_rules(tmp_path):
    services, _ = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    proposal = services.actions.generate({**_payload(), "pyramid_enabled": True})
    _, artifact = services.artifacts.read_json("actions/proposals", proposal["artifact_id"])
    policy = artifact["policy"]
    assert policy["execution_policy_version"] == "v4-portfolio-execution-1"
    assert policy["pyramid_enabled"] is True
    assert policy["pyramid_fraction"] == "0.5"
    assert policy["sell_before_buy"] is True
    assert policy["entry_timing"] == "next_tradable_open"
    assert policy["cash_resize"] == "actual_open_with_available_cash"
    assert policy["zero_unit_buy"] == "remain_pending"


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
    endpoint = "/api/v2/actions/execution-policy-parity"
    assert client.post(endpoint, json={"v3_policy": baseline}).status_code == 201
    response = client.post(endpoint, json={"v3_policy": baseline})
    assert response.status_code == 201
    artifact_id = response.json["parity_artifact_id"]
    assert response.json["parity"] is True
    readback = client.get(f"{endpoint}/{artifact_id}")
    assert readback.status_code == 200
    assert readback.json["data"]["execution_policy_version"] == "v4-portfolio-execution-1"


def test_removed_member_cannot_be_bought_from_old_rankings_or_manual_entry(tmp_path):
    services, instrument_id = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    pending_old = services.actions.generate(_payload())
    services.market.upsert_instruments([
        TrackedInstrument("replacement", "INE000000002", "NEW", "NSE", "43", date(2026, 9, 5)),
    ])
    services.market.create_universe_snapshot(
        snapshot_id="action-new-universe", index_name="NIFTY 500",
        snapshot_date=date(2026, 9, 5), source_url="fixture://nse",
        raw_csv=b"NEW", members=[{"isin": "INE000000002", "symbol": "NEW",
            "company_name": "NEW", "industry": "IT", "series": "EQ"}],
    )
    with pytest.raises(DomainValidationError, match="outside the current NSE snapshot"):
        services.actions.decide(pending_old["proposal_id"], "APPROVED")
    proposal = services.actions.generate(_payload())
    assert all(item["type"] != "BUY" or item["instrument_id"] != instrument_id
               for item in proposal["decisions"])
    with pytest.raises(DomainValidationError, match="outside the current NSE snapshot"):
        services.actions.create_manual({
            "account_id": "paper", "action_date": "2026-09-08", "reason": "old ranking",
            "entries": [{"symbol": "ABC", "exchange": "NSE", "side": "BUY",
                         "units": 1, "price": "100"}],
        })


def test_momentum_replay_exits_removed_member_at_next_observed_open_only(tmp_path):
    services, instrument_id = _services(tmp_path)
    decision = date(2026, 9, 8)
    # No benchmark bar is stored for September 9; execution uses the next observed session.
    target = date(2026, 9, 10)
    services.market.upsert_instruments([
        TrackedInstrument("benchmark", "INDEX:NIFTY 500", "NIFTY 500", "NSE", "500", date(2026, 9, 4)),
        TrackedInstrument("replacement", "INE000000002", "NEW", "NSE", "43", decision),
    ])
    services.market.upsert_bars("benchmark", [
        NormalizedBar("benchmark", day, 100, 101, 99, 100, 0)
        for day in (date(2026, 9, 7), decision, target)
    ], "benchmark-sessions")
    services.market.upsert_bars(instrument_id, [
        NormalizedBar(instrument_id, decision, 102, 105, 100, 103, 1000),
        NormalizedBar(instrument_id, target, 110, 112, 109, 111, 1000),
    ], "exit-bars-first")
    services.market.upsert_indicators(
        services.research._indicator_set("momentum", None), date(2026, 9, 4),
        {instrument_id: {"atrr_14": 5, "close": 100}}, "risk-inputs-after-history",
    )
    services.market.create_universe_snapshot(
        snapshot_id="after-abc-removal", index_name="NIFTY 500", snapshot_date=decision,
        source_url="fixture://nse", raw_csv=b"NEW",
        members=[{"isin": "INE000000002", "symbol": "NEW", "company_name": "NEW",
                  "industry": "IT", "series": "EQ"}],
    )
    command = {"strategy_id": "momentum", "start_date": "2026-09-07",
               "end_date": decision.isoformat()}
    first = services.backtests.execute(command)
    _, first_report = services.artifacts.read_json("runs/backtests", first["artifact_id"])
    first_exit = next(fill for fill in first_report["fills"]
                      if fill["decision_type"] == "UNIVERSE_EXIT")
    assert first_exit["as_of_date"] == target.isoformat()
    assert first_exit["decision_date"] == decision.isoformat()
    assert first_exit["universe_snapshot_id"] == "after-abc-removal"
    assert first_exit["price_snapshot_id"] == "exit-bars-first"
    assert Decimal(str(first_exit["price"])) == Decimal(110)
    assert first_report["equity_curve"][-1]["date"] == decision.isoformat()
    assert first_report["post_period_exit_fills"] == [first_exit]
    assert first_report["trade_counts"]["sell"] == 0
    in_period = services.backtests.execute({**command, "end_date": target.isoformat()})
    _, in_period_report = services.artifacts.read_json("runs/backtests", in_period["artifact_id"])
    assert any(fill["decision_type"] == "UNIVERSE_EXIT" and fill["as_of_date"] == target.isoformat()
               for fill in in_period_report["fills"])
    assert not any(fill["side"] == "BUY" and fill["as_of_date"] == target.isoformat()
                   for fill in in_period_report["fills"])

    services.market.upsert_bars(instrument_id, [
        NormalizedBar(instrument_id, target, 150, 152, 149, 151, 1000),
    ], "exit-bars-revised")
    services.market.upsert_indicators(
        services.research._indicator_set("momentum", None), date(2026, 9, 4),
        {instrument_id: {"atrr_14": 5, "close": 100}}, "risk-inputs-after-revision",
    )
    second = services.backtests.execute(command)
    _, second_report = services.artifacts.read_json("runs/backtests", second["artifact_id"])
    second_exit = next(fill for fill in second_report["fills"]
                       if fill["decision_type"] == "UNIVERSE_EXIT")
    assert second["artifact_id"] != first["artifact_id"]
    assert Decimal(str(second_exit["price"])) == Decimal(150)
    assert second_report["equity_curve"] == first_report["equity_curve"]
    assert services.artifacts.read_json("runs/backtests", first["artifact_id"])[1] == first_report
    with sqlite_connection(services.database) as connection:
        connection.execute("DELETE FROM market_bars WHERE instrument_id=? AND as_of_date=?",
                           (instrument_id, target.isoformat()))
    with pytest.raises(DomainValidationError, match="missing declared universe-exit open"):
        services.backtests.execute(command)
