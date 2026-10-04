from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.indicators.registry import PandasTaAdapter
from src.domains.market_data import NormalizedBar
from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.domains.reference_data import TrackedInstrument
from src.domains.strategies.positional_trend_backtest import Policy, simulate
from src.gates.composition import ApplicationServices
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.gates.workflows.portfolio_actions import ActionJobs
from src.gates.workflows.positional_trend import PositionalTrendJobs
from src.platform_kernel import ArtifactStore, DomainValidationError, Money, Quantity
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
    source = (Path(__file__).resolve().parents[3] / "strategies" / "momentum.yml").read_text()
    source = (
        source.replace("version: 1.2.0", "version: 1.2.1")
        .replace("max_positions: 15", "max_positions: 1")
        .replace("exit_threshold: 40", "exit_threshold: 41")
    )
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
        "reference/fundamentals",
        "fundamentals-action-1",
        {
            "as_of_date": "2026-09-01",
            "values": {"missing-is-not-used": {"eps": "1", "debt_equity": "2"}},
        },
    )
    proposal = services.actions.generate(
        {**_payload(), "fundamentals_artifact_id": fundamentals.artifact_id, "min_eps": "5"}
    )
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


def test_removed_member_cannot_be_bought_from_old_rankings_or_manual_entry(tmp_path):
    services, instrument_id = _services(tmp_path)
    services.ledger.open_account("paper", Money(1000))
    pending_old = services.actions.generate(_payload())
    services.market.upsert_instruments(
        [
            TrackedInstrument("replacement", "INE000000002", "NEW", "NSE", "43", date(2026, 9, 5)),
        ]
    )
    services.market.create_universe_snapshot(
        snapshot_id="action-new-universe",
        index_name="NIFTY 500",
        snapshot_date=date(2026, 9, 5),
        source_url="fixture://nse",
        raw_csv=b"NEW",
        members=[
            {
                "isin": "INE000000002",
                "symbol": "NEW",
                "company_name": "NEW",
                "industry": "IT",
                "series": "EQ",
            }
        ],
    )
    with pytest.raises(DomainValidationError, match="outside the current NSE snapshot"):
        services.actions.decide(pending_old["proposal_id"], "APPROVED")
    proposal = services.actions.generate(_payload())
    assert all(
        item["type"] != "BUY" or item["instrument_id"] != instrument_id
        for item in proposal["decisions"]
    )
    with pytest.raises(DomainValidationError, match="outside the current NSE snapshot"):
        services.actions.create_manual(
            {
                "account_id": "paper",
                "action_date": "2026-09-08",
                "reason": "old ranking",
                "entries": [
                    {"symbol": "ABC", "exchange": "NSE", "side": "BUY", "units": 1, "price": "100"}
                ],
            }
        )


def test_momentum_replay_exits_removed_member_at_next_observed_open_only(tmp_path):
    services, instrument_id = _services(tmp_path)
    decision = date(2026, 9, 8)
    # No benchmark bar is stored for September 9; execution uses the next observed session.
    target = date(2026, 9, 10)
    services.market.upsert_instruments(
        [
            TrackedInstrument(
                "benchmark", "INDEX:NIFTY 500", "NIFTY 500", "NSE", "500", date(2026, 9, 4)
            ),
            TrackedInstrument("replacement", "INE000000002", "NEW", "NSE", "43", decision),
        ]
    )
    services.market.upsert_bars(
        "benchmark",
        [
            NormalizedBar("benchmark", day, 100, 101, 99, 100, 0)
            for day in (date(2026, 9, 7), decision, target)
        ],
        "benchmark-sessions",
    )
    services.market.upsert_bars(
        instrument_id,
        [
            NormalizedBar(instrument_id, decision, 102, 105, 100, 103, 1000),
            NormalizedBar(instrument_id, target, 110, 112, 109, 111, 1000),
        ],
        "exit-bars-first",
    )
    services.market.upsert_indicators(
        services.research._indicator_set("momentum", None),
        date(2026, 9, 4),
        {instrument_id: {"atrr_14": 5, "close": 100}},
        "risk-inputs-after-history",
    )
    services.market.create_universe_snapshot(
        snapshot_id="after-abc-removal",
        index_name="NIFTY 500",
        snapshot_date=decision,
        source_url="fixture://nse",
        raw_csv=b"NEW",
        members=[
            {
                "isin": "INE000000002",
                "symbol": "NEW",
                "company_name": "NEW",
                "industry": "IT",
                "series": "EQ",
            }
        ],
    )
    command = {
        "strategy_id": "momentum",
        "start_date": "2026-09-07",
        "end_date": decision.isoformat(),
    }
    first = services.backtests.execute(command)
    _, first_report = services.artifacts.read_json("runs/backtests", first["artifact_id"])
    first_exit = next(
        fill for fill in first_report["fills"] if fill["decision_type"] == "UNIVERSE_EXIT"
    )
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
    assert any(
        fill["decision_type"] == "UNIVERSE_EXIT" and fill["as_of_date"] == target.isoformat()
        for fill in in_period_report["fills"]
    )
    assert not any(
        fill["side"] == "BUY" and fill["as_of_date"] == target.isoformat()
        for fill in in_period_report["fills"]
    )

    services.market.upsert_bars(
        instrument_id,
        [
            NormalizedBar(instrument_id, target, 150, 152, 149, 151, 1000),
        ],
        "exit-bars-revised",
    )
    services.market.upsert_indicators(
        services.research._indicator_set("momentum", None),
        date(2026, 9, 4),
        {instrument_id: {"atrr_14": 5, "close": 100}},
        "risk-inputs-after-revision",
    )
    second = services.backtests.execute(command)
    _, second_report = services.artifacts.read_json("runs/backtests", second["artifact_id"])
    second_exit = next(
        fill for fill in second_report["fills"] if fill["decision_type"] == "UNIVERSE_EXIT"
    )
    assert second["artifact_id"] != first["artifact_id"]
    assert Decimal(str(second_exit["price"])) == Decimal(150)
    assert second_report["equity_curve"] == first_report["equity_curve"]
    assert services.artifacts.read_json("runs/backtests", first["artifact_id"])[1] == first_report
    with sqlite_connection(services.database) as connection:
        connection.execute(
            "DELETE FROM market_bars WHERE instrument_id=? AND as_of_date=?",
            (instrument_id, target.isoformat()),
        )
    with pytest.raises(DomainValidationError, match="missing declared universe-exit open"):
        services.backtests.execute(command)


def _setup(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    text = (
        Path(__file__).resolve().parents[3] / "strategies/positional_trend_following.yml"
    ).read_text()
    revision = definitions.create_from_yaml(text)
    definitions.activate(revision["revision_id"])
    runtime = StrategyRuntime(definitions)
    days = [(date(2022, 1, 1) + timedelta(days=i)).isoformat() for i in range(110)]
    bars = [
        {
            "as_of_date": day,
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 2_000_000,
            "snapshot_id": str(uuid4()),
        }
        for day in days
    ]
    source = {"a": (bars, {"symbol": "A", "exchange": "NSE", "isin": "ISIN-A"})}
    market = SimpleNamespace(
        path=database,
        histories=lambda *_, **__: source,
        session_dates=lambda *_, exchange="NSE": days if exchange == "NSE" else [],
        latest_universe_snapshot=lambda _: {"snapshot_id": "snapshot-a", "snapshot_date": days[-1]},
        universe_snapshot_as_of=lambda *_: {"snapshot_id": "snapshot-a", "snapshot_date": days[-1]},
        universe_snapshot_members=lambda *_args, **_kwargs: [{"isin": "ISIN-A"}],
    )
    jobs = PositionalTrendJobs(market, publisher, runtime)
    return jobs, source, runtime, text, publisher, days


def test_live_sizing_ignores_costs_and_replay_retains_round_trip_fees(tmp_path, monkeypatch):
    jobs, _, runtime, _, publisher, _ = _setup(tmp_path)
    days = ["2022-01-03", "2022-01-04"]
    bar = {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 2_000_000}
    rows = [
        {
            "instrument_id": symbol,
            "symbol": symbol,
            "rank": rank,
            "signal_date": days[0],
            "close": 100,
            "adx14": 40 - rank,
            "adv30": 200_000_000,
            "initial_stop_anchor": 90,
            "filtered": True,
            "exit_signal": False,
        }
        for rank, symbol in enumerate(("A", "B"), 1)
    ]
    market = SimpleNamespace(
        session_dates=lambda *_, **__: days,
        bars=lambda *_, **__: [{**bar, "as_of_date": days[1], "snapshot_id": "open-snapshot"}],
        latest_universe_snapshot=lambda _: {"snapshot_id": "current-snapshot"},
        universe_snapshot_members=lambda *_, **__: [{"isin": "ISIN-A"}, {"isin": "ISIN-B"}],
        tracked_instruments=lambda: [
            {"instrument_id": "A", "isin": "ISIN-A", "exchange": "NSE"},
            {"instrument_id": "B", "isin": "ISIN-B", "exchange": "NSE"},
        ],
    )
    signal = publisher.publish_json("research/positional-trend-signals", str(uuid4()), {"signals": rows})
    service = SimpleNamespace(read_signals=lambda *_, **__: (signal.artifact_id, {"signals": rows}))
    ledger = Ledger(jobs.market.path)
    ledger.open_account("paper", Money(10_000))
    actions = ActionJobs(
        jobs.market.path, market, SimpleNamespace(runtime=runtime), ledger, publisher, service
    )
    proposal = actions.generate(
        {"account_id": "paper", "strategy_id": "positional_trend_following", "action_date": days[1]}
    )
    monkeypatch.setattr(
        "src.domains.strategies.positional_trend_backtest.feature_series",
        lambda history, sessions, symbol, rules: [row for row in rows if row["symbol"] == symbol],
    )
    histories = {
        symbol: (symbol, [{**bar, "as_of_date": day} for day in days]) for symbol in ("A", "B")
    }
    result = simulate(
        histories, days, policy=Policy(initial_capital=10_000), start_date=days[0], end_date=days[1]
    )
    assert [item["units"] for item in proposal["decisions"]] == [10, 10]
    market.latest_universe_snapshot = lambda _: {"snapshot_id": "new-current-snapshot"}
    market.universe_snapshot_members = lambda *_, **__: [{"isin": "ISIN-A"}]
    after_removal = actions.generate(
        {"account_id": "paper", "strategy_id": "positional_trend_following", "action_date": days[1]}
    )
    assert after_removal["proposal_id"] != proposal["proposal_id"]
    assert [
        item["instrument_id"] for item in after_removal["decisions"] if item["type"] == "BUY"
    ] == ["A"]
    assert [item["shares"] for item in result["fills"]] == [10, 9]
    assert result["performance"]["total_fees"] > 0


def test_held_exit_survives_missing_open_and_universe_removal(tmp_path, monkeypatch):
    jobs, _, runtime, _, publisher, _ = _setup(tmp_path)
    days = ["2022-01-03", "2022-01-04", "2022-01-05"]
    bar = {
        "as_of_date": days[0],
        "open": 100,
        "high": 101,
        "low": 89,
        "close": 90,
        "volume": 2_000_000,
        "snapshot_id": "held-close",
    }
    identity = {"symbol": "HELD", "isin": "ISIN-H", "exchange": "NSE"}
    market = SimpleNamespace(
        session_dates=lambda start, end, **__: [day for day in days if day <= end.isoformat()],
        histories=lambda *_, **__: {"H": ([bar], identity)},
        bars=lambda instrument, start, end, **__: (
            [{**bar, "as_of_date": days[2], "open": 92, "snapshot_id": "held-open"}]
            if start.isoformat() == days[2]
            else []
        ),
    )
    # The held NSE identity is read directly even when absent from the current universe.
    monkeypatch.setattr(
        "src.domains.strategies.positional_trend.feature_series",
        lambda *args: [
            {
                "symbol": "HELD",
                "signal_date": days[0],
                "close": 90,
                "exit_signal": True,
            }
        ],
    )
    ledger = Ledger(jobs.market.path)
    ledger.open_account("paper", Money(10_000))
    ledger.record_fills(
        "paper",
        "held-entry",
        0,
        [
            Fill("H", date.fromisoformat(days[0]), FillSide.BUY, Quantity(10), Money(100)),
        ],
    )
    signal = publisher.publish_json("research/positional-trend-signals", str(uuid4()), {"signals": []})
    service = SimpleNamespace(read_signals=lambda *_, **__: (signal.artifact_id, {"signals": []}))
    actions = ActionJobs(
        jobs.market.path, market, SimpleNamespace(runtime=runtime), ledger, publisher, service
    )
    first = actions.generate(
        {"account_id": "paper", "strategy_id": "positional_trend_following", "action_date": days[1]}
    )
    assert first["decisions"][0]["type"] == "NO_ACTION"
    _, artifact = publisher.store.read_json("actions/proposals", first["proposal_id"])
    assert artifact["skipped_candidates"][0]["reason"] == "exit_waiting_for_valid_open"
    second = actions.generate(
        {"account_id": "paper", "strategy_id": "positional_trend_following", "action_date": days[2]}
    )
    assert second["decisions"][0]["type"] == "SELL"
    assert second["decisions"][0]["units"] == 10
    assert second["decisions"][0]["signal_date"] == days[0]
