"""Strategy 4 artifact freshness, registry contracts and replay/proposal parity."""

import csv
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml

from src.application.action_jobs import ActionJobs
from src.application.catalog import ArtifactCatalog
from src.application.composition import ApplicationServices
from src.application.market_repository import TrackedInstrument
from src.application.positional_trend_backtest import Policy, simulate
from src.application.positional_trend_jobs import PositionalTrendJobs
from src.application.publication import ArtifactPublisher
from src.application.strategy_definitions import StrategyDefinitions
from src.application.strategy_runtime import StrategyRuntime
from src.execution_gateway import Ledger
from src.indicators.custom import INSTRUMENT_IMPLEMENTATIONS, INSTRUMENT_SERIES_IMPLEMENTATIONS
from src.indicators.registry import PandasTaAdapter
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore, DomainValidationError, Money, Quantity
from src.portfolio_accounting import Fill, FillSide


def _setup(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    text = (Path(__file__).resolve().parents[1] / "strategies/positional_trend_following.yml").read_text()
    revision = definitions.create_from_yaml(text)
    definitions.activate(revision["revision_id"])
    runtime = StrategyRuntime(definitions)
    days = [(date(2022, 1, 1) + timedelta(days=i)).isoformat() for i in range(110)]
    bars = [{"as_of_date": day, "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": 2_000_000, "snapshot_id": str(uuid4())} for day in days]
    source = {"a": (bars, {"symbol": "A", "exchange": "NSE", "isin": "ISIN-A"})}
    market = SimpleNamespace(
        path=database, histories=lambda *_, **__: source,
        session_dates=lambda *_, exchange="NSE": days if exchange == "NSE" else [],
        latest_universe_snapshot=lambda _: {"snapshot_id": "snapshot-a", "snapshot_date": days[-1]},
        universe_snapshot_members=lambda *_args, **_kwargs: [{"isin": "ISIN-A"}],
    )
    csv = tmp_path / "nifty500.csv"
    csv.write_text("Symbol,Series,ISIN Code\nA,EQ,ISIN-A\n")
    jobs = PositionalTrendJobs(market, publisher, runtime, csv)
    return jobs, source, runtime, text, publisher, days


def test_signals_are_reused_only_for_identical_inputs(tmp_path):
    jobs, source, runtime, text, _, days = _setup(tmp_path)
    day = date.fromisoformat(days[-1])
    payload = {"as_of_date": day.isoformat()}
    first = jobs.build_signals(payload)
    assert jobs.build_signals(payload)["reused"]
    assert jobs.read_signals(day)[0] == first["artifact_id"]
    # Same prices with different source evidence must not silently reuse lineage.
    source["a"][0][-1]["snapshot_id"] = str(uuid4())
    assert jobs.read_signals(day) is None
    second = jobs.build_signals(payload)
    assert second["artifact_id"] != first["artifact_id"]
    revision = runtime.definitions.create_from_yaml(text.replace("adx_minimum: 25", "adx_minimum: 30"))
    runtime.definitions.activate(revision["revision_id"])
    assert jobs.read_signals(day) is None
    assert jobs.build_signals(payload)["artifact_id"] != second["artifact_id"]


def test_registry_exposes_full_date_keyed_series(tmp_path):
    _, source, _, _, _, _ = _setup(tmp_path)
    bars = source["a"][0]
    key = "custom.positional_trend_features"
    rows = INSTRUMENT_SERIES_IMPLEMENTATIONS[key](list(reversed(bars)))
    assert len(rows) > 1
    assert INSTRUMENT_IMPLEMENTATIONS[key](bars) == rows[bars[-1]["as_of_date"]]


@pytest.mark.parametrize("field,value", [("adx_period", 14.5), ("minimum_adtv", float("inf"))])
def test_indicator_rules_reject_invalid_numbers(tmp_path, field, value):
    _, _, runtime, text, _, _ = _setup(tmp_path)
    definition = yaml.safe_load(text)
    definition["signal_rules"][field] = value
    with pytest.raises(DomainValidationError):
        runtime.definitions.create_from_yaml(yaml.safe_dump(definition))


def test_proposals_and_replay_size_competing_entries_after_fees(tmp_path, monkeypatch):
    jobs, _, runtime, _, publisher, _ = _setup(tmp_path)
    days = ["2022-01-03", "2022-01-04"]
    bar = {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 2_000_000}
    rows = [{"instrument_id": symbol, "symbol": symbol, "rank": rank,
             "signal_date": days[0], "close": 100, "adx14": 40 - rank,
             "adv30": 200_000_000, "initial_stop_anchor": 90, "filtered": True,
             "exit_signal": False} for rank, symbol in enumerate(("A", "B"), 1)]
    market = SimpleNamespace(
        session_dates=lambda *_, **__: days,
        bars=lambda *_, **__: [{**bar, "as_of_date": days[1], "snapshot_id": "open-snapshot"}],
    )
    signal = publisher.publish_json("research/strategy4-signals", str(uuid4()), {"signals": rows})
    service = SimpleNamespace(read_signals=lambda *_, **__: (signal.artifact_id, {"signals": rows}))
    ledger = Ledger(jobs.market.path)
    ledger.open_account("paper", Money(10_000))
    actions = ActionJobs(jobs.market.path, market, SimpleNamespace(runtime=runtime), ledger, publisher, service)
    proposal = actions.generate({"account_id": "paper", "strategy_id": "positional_trend_following",
                                 "action_date": days[1]})
    monkeypatch.setattr("src.application.positional_trend_backtest.feature_series",
                        lambda history, sessions, symbol, rules: [row for row in rows if row["symbol"] == symbol])
    histories = {symbol: (symbol, [{**bar, "as_of_date": day} for day in days]) for symbol in ("A", "B")}
    result = simulate(histories, days, policy=Policy(initial_capital=10_000), start_date=days[0], end_date=days[1])
    assert [item["units"] for item in proposal["decisions"]] == [item["shares"] for item in result["fills"]] == [10, 9]


def test_held_exit_survives_missing_open_and_universe_removal(tmp_path, monkeypatch):
    jobs, _, runtime, _, publisher, _ = _setup(tmp_path)
    days = ["2022-01-03", "2022-01-04", "2022-01-05"]
    bar = {"as_of_date": days[0], "open": 100, "high": 101, "low": 89,
           "close": 90, "volume": 2_000_000, "snapshot_id": "held-close"}
    identity = {"symbol": "HELD", "isin": "ISIN-H", "exchange": "BSE"}
    market = SimpleNamespace(
        session_dates=lambda start, end, **__: [day for day in days if day <= end.isoformat()],
        histories=lambda *_, **__: {"H": ([bar], identity)},
        bars=lambda instrument, start, end, **__: [
            {**bar, "as_of_date": days[2], "open": 92, "snapshot_id": "held-open"}
        ] if start.isoformat() == days[2] else [],
    )
    # The held BSE identity is read directly even when absent from the current universe.
    monkeypatch.setattr("src.application.positional_trend.feature_series", lambda *args: [{
        "symbol": "HELD", "signal_date": days[0], "close": 90, "exit_signal": True,
    }])
    ledger = Ledger(jobs.market.path)
    ledger.open_account("paper", Money(10_000))
    ledger.record_fills("paper", "held-entry", 0, [
        Fill("H", date.fromisoformat(days[0]), FillSide.BUY, Quantity(10), Money(100)),
    ])
    signal = publisher.publish_json("research/strategy4-signals", str(uuid4()), {"signals": []})
    service = SimpleNamespace(read_signals=lambda *_, **__: (signal.artifact_id, {"signals": []}))
    actions = ActionJobs(jobs.market.path, market, SimpleNamespace(runtime=runtime), ledger, publisher, service)
    first = actions.generate({"account_id": "paper", "strategy_id": "positional_trend_following", "action_date": days[1]})
    assert first["decisions"][0]["type"] == "NO_ACTION"
    _, artifact = publisher.store.read_json("actions/proposals", first["proposal_id"])
    assert artifact["skipped_candidates"][0]["reason"] == "exit_waiting_for_valid_open"
    second = actions.generate({"account_id": "paper", "strategy_id": "positional_trend_following", "action_date": days[2]})
    assert second["decisions"][0]["type"] == "SELL"
    assert second["decisions"][0]["units"] == 10
    assert second["decisions"][0]["signal_date"] == days[0]


def test_v4_real_indicators_signals_actions_and_cataloged_backtest_agree(tmp_path):
    services = ApplicationServices.create(tmp_path)
    member = {"ISIN Code": "INE000A01000", "Symbol": "FIXTURE", "Series": "EQ"}
    instrument = str(uuid4())
    start = date(2022, 1, 1)
    services.market.upsert_instruments([
        TrackedInstrument(instrument, member["ISIN Code"], member["Symbol"], "NSE", "42", start),
    ])
    services.market.create_universe_snapshot(
        snapshot_id="fixture-nifty500", index_name="NIFTY 500", snapshot_date=start,
        source_url="fixture", raw_csv=b"fixture", members=[{
            "isin": member["ISIN Code"], "symbol": member["Symbol"],
            "company_name": "Fixture", "industry": "Fixture", "series": "EQ",
        }],
    )
    bars = []
    for index in range(108):
        close = Decimal(100 if index < 70 else min(187, 100 + 3 * (index - 70)))
        opening = close
        if index == 105:
            opening = close = Decimal(197)
        elif index == 106:
            opening, close = Decimal(198), Decimal(170)
        elif index == 107:
            opening = close = Decimal(171)
        bars.append(NormalizedBar(instrument, start + timedelta(days=index), opening,
                                  max(opening, close) + 1, min(opening, close) - 1,
                                  close, 2_000_000))
    services.market.upsert_bars(instrument, bars, "v4-fixture-bars")
    signal_day, buy_day, sell_day = (start + timedelta(days=index) for index in (105, 106, 107))
    signal_result = services.positional_trend.build_signals({"as_of_date": signal_day.isoformat()})
    assert signal_result["signal_count"] == 1
    services.ledger.open_account("paper", Money(500_000))
    buy = services.actions.generate({"account_id": "paper", "strategy_id": "positional_trend_following",
                                     "action_date": buy_day.isoformat()})["decisions"][0]
    assert buy["type"] == "BUY"
    services.ledger.record_fills("paper", "fixture-confirmed-buy", 0, [
        Fill(instrument, buy_day, FillSide.BUY, Quantity(buy["units"]),
             Money(Decimal(buy["execution_price"])), Money(Decimal(buy["fee"]))),
    ])
    sell = services.actions.generate({"account_id": "paper", "strategy_id": "positional_trend_following",
                                      "action_date": sell_day.isoformat()})["decisions"][0]
    assert sell["type"] == "SELL"
    replay_run = services.backtests.execute({"strategy_id": "positional_trend_following",
                                            "start_date": signal_day.isoformat(),
                                            "end_date": sell_day.isoformat()})
    _, report = services.artifacts.read_json("runs/backtests", replay_run["artifact_id"])
    assert [fill["side"] for fill in report["fills"]] == ["BUY", "SELL"]
    assert [fill["shares"] for fill in report["fills"]] == [buy["units"], sell["units"]]
    assert [Decimal(str(fill["price"])) for fill in report["fills"]] == [
        Decimal(buy["execution_price"]), Decimal(sell["execution_price"])]
