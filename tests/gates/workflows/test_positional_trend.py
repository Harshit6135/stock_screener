from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.indicators.registry import PandasTaAdapter
from src.domains.market_data import NormalizedBar
from src.domains.portfolio_accounting import Fill, FillSide
from src.domains.reference_data import TrackedInstrument
from src.gates.composition import ApplicationServices
from src.gates.repositories import MarketRepository
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.gates.workflows.positional_trend import PositionalTrendJobs
from src.platform_kernel import ArtifactStore, DomainValidationError, Money, Quantity


class TestSnapshotDrivenStrategy:
    def test_snapshot_nifty500_universe_resolves_from_snapshot(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        observed = date(2026, 1, 1)
        snap_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap_id,
            index_name="NIFTY 500",
            snapshot_date=observed,
            source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,A,A Co,IT,EQ\nIN0000000002,B,B Co,IT,EQ",
            members=[
                {
                    "isin": "IN0000000001",
                    "symbol": "A",
                    "company_name": "A Co",
                    "industry": "IT",
                    "series": "EQ",
                },
                {
                    "isin": "IN0000000002",
                    "symbol": "B",
                    "company_name": "B Co",
                    "industry": "IT",
                    "series": "EQ",
                },
            ],
        )
        from src.gates.workflows.positional_trend import PositionalTrendJobs

        trend = PositionalTrendJobs(market, MagicMock(), MagicMock())
        members, digest, metadata = trend._members("SNAPSHOT_NIFTY500")
        assert digest == trend._members("SNAPSHOT_NIFTY500")[1]
        assert members == {"IN0000000001", "IN0000000002"}
        assert metadata["source"] == "SNAPSHOT_NIFTY500"
        assert metadata["snapshot_id"] == snap_id
        assert metadata["member_count"] == 2
        with pytest.raises(DomainValidationError, match="SNAPSHOT_NIFTY500"):
            trend._members("APPLICATION_MCAP500")
        with pytest.raises(DomainValidationError, match="universe is invalid"):
            trend.build_signals(
                {"as_of_date": observed.isoformat(), "universe": "APPLICATION_MCAP500"}
            )


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
    revision = runtime.definitions.create_from_yaml(
        text.replace("adx_minimum: 25", "adx_minimum: 30")
    )
    runtime.definitions.activate(revision["revision_id"])
    assert jobs.read_signals(day) is None
    assert jobs.build_signals(payload)["artifact_id"] != second["artifact_id"]


def test_v4_real_indicators_signals_actions_and_cataloged_backtest_agree(tmp_path):
    services = ApplicationServices.create(tmp_path)
    member = {"ISIN Code": "INE000A01000", "Symbol": "FIXTURE", "Series": "EQ"}
    instrument = str(uuid4())
    start = date(2022, 1, 1)
    services.market.upsert_instruments(
        [
            TrackedInstrument(
                instrument, member["ISIN Code"], member["Symbol"], "NSE", "42", start
            ),
        ]
    )
    services.market.create_universe_snapshot(
        snapshot_id="fixture-nifty500",
        index_name="NIFTY 500",
        snapshot_date=start,
        source_url="fixture",
        raw_csv=b"fixture",
        members=[
            {
                "isin": member["ISIN Code"],
                "symbol": member["Symbol"],
                "company_name": "Fixture",
                "industry": "Fixture",
                "series": "EQ",
            }
        ],
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
        bars.append(
            NormalizedBar(
                instrument,
                start + timedelta(days=index),
                opening,
                max(opening, close) + 1,
                min(opening, close) - 1,
                close,
                2_000_000,
            )
        )
    services.market.upsert_bars(instrument, bars, "v4-fixture-bars")
    signal_day, buy_day, sell_day = (start + timedelta(days=index) for index in (105, 106, 107))
    signal_result = services.positional_trend.build_signals({"as_of_date": signal_day.isoformat()})
    assert signal_result["signal_count"] == 1
    services.ledger.open_account("paper", Money(200_000))
    buy = services.actions.generate(
        {
            "account_id": "paper",
            "strategy_id": "positional_trend_following",
            "action_date": buy_day.isoformat(),
        }
    )["decisions"][0]
    assert buy["type"] == "BUY"
    services.ledger.record_fills(
        "paper",
        "fixture-confirmed-buy",
        0,
        [
            Fill(
                instrument,
                buy_day,
                FillSide.BUY,
                Quantity(buy["units"]),
                Money(Decimal(buy["execution_price"])),
                Money(Decimal(buy["fee"])),
            ),
        ],
    )
    sell = services.actions.generate(
        {
            "account_id": "paper",
            "strategy_id": "positional_trend_following",
            "action_date": sell_day.isoformat(),
        }
    )["decisions"][0]
    assert sell["type"] == "SELL"
    with pytest.raises(DomainValidationError, match="universe is invalid"):
        services.actions.generate(
            {
                "account_id": "paper",
                "strategy_id": "positional_trend_following",
                "action_date": sell_day.isoformat(),
                "universe": "APPLICATION_MCAP500",
            }
        )
    with pytest.raises(DomainValidationError, match="universe is invalid"):
        services.backtests.execute(
            {
                "strategy_id": "positional_trend_following",
                "start_date": signal_day.isoformat(),
                "end_date": sell_day.isoformat(),
                "universe": "APPLICATION_MCAP500",
            }
        )
    replay_run = services.backtests.execute(
        {
            "strategy_id": "positional_trend_following",
            "start_date": signal_day.isoformat(),
            "end_date": sell_day.isoformat(),
        }
    )
    _, report = services.artifacts.read_json("runs/backtests", replay_run["artifact_id"])
    assert [fill["side"] for fill in report["fills"]] == ["BUY", "SELL"]
    assert [fill["shares"] for fill in report["fills"]] == [buy["units"], sell["units"]]
    assert [Decimal(str(fill["price"])) for fill in report["fills"]] == [
        Decimal(buy["execution_price"]),
        Decimal(sell["execution_price"]),
    ]
