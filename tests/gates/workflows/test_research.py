from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.market_data import NormalizedBar
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.research import ResearchJobs
from src.platform_kernel import ArtifactStore, SqliteArtifactStore
from src.platform_kernel.sqlite import sqlite_connection

DAY = date(2026, 1, 5)


def setup_market(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    publisher = ArtifactPublisher(SqliteArtifactStore(database), ArtifactCatalog(database))
    return market, publisher


def seed_snapshot(market, snapshot_id, day, instruments):
    market.create_universe_snapshot(
        snapshot_id=snapshot_id,
        index_name="NIFTY 500",
        snapshot_date=day,
        source_url="fixture://nse",
        raw_csv=snapshot_id.encode(),
        members=[
            {
                "isin": isin,
                "symbol": symbol,
                "company_name": symbol,
                "industry": "IT",
                "series": "BE",
            }
            for isin, symbol in instruments
        ],
    )


def test_quality_warning_does_not_remove_stock_from_research(tmp_path):

    market, publisher = setup_market(tmp_path)
    instruments = [
        TrackedInstrument("a", "IN0000000001", "AAA", "NSE", "1", DAY),
        TrackedInstrument("b", "IN0000000002", "BBB", "NSE", "2", DAY),
    ]
    market.upsert_instruments(instruments)
    seed_snapshot(market, "research", DAY, [("IN0000000001", "AAA"), ("IN0000000002", "BBB")])
    dates = [DAY + timedelta(days=i) for i in range(5)]
    for instrument in instruments:
        prices = (
            [100, 130, 131, 132, 133]
            if instrument.instrument_id == "a"
            else [100, 101, 102, 103, 104]
        )
        market.upsert_bars(
            instrument.instrument_id,
            [
                NormalizedBar(instrument.instrument_id, day, price, price, price, price, 10)
                for day, price in zip(dates, prices)
            ],
            "rank-bars",
        )
    assert market.quality_events(instrument_id="a", check_type="close_gap")

    class Runtime:
        def strategy_kind(self, strategy):
            return "factor_score"

        def strategy_ids(self):
            return ("momentum",)

        def revision(self, strategy):
            return {"revision_id": "rev", "definition": {"score": {"factor_modifiers": []}}}

        def factor_weights(self, strategy):
            return {"trend": 1.0}

        def factor_multiplier(self, strategy, factor, values):
            return 1.0

        def benchmark(self, strategy):
            return None

        def compute_series(self, strategy, bars, benchmark):
            return {
                bar["as_of_date"]: {
                    "factors": {"trend": float(bar["close"])},
                    "penalty": 1.0,
                    "penalty_reasons": [],
                }
                for bar in bars
            }

        def cross_section(self, strategy, values):
            return None

    research = ResearchJobs(market.path, market, publisher, Runtime())
    result = research.rebuild_range(
        {
            "start_date": DAY.isoformat(),
            "end_date": dates[-1].isoformat(),
            "strategies": ["momentum"],
            "trading_dates": [day.isoformat() for day in dates],
        },
        SimpleNamespace(checkpoint=lambda **kwargs: None),
    )
    assert result["strategies"]["momentum"]["scored_rows"] == 10
    assert market.instrument_by_id("a") is not None


class _Market:
    def __init__(self):
        start = date(2025, 1, 6)
        self.values = {}
        for instrument, symbol, offset in (("a", "AAA", 10), ("b", "BBB", 20)):
            bars = [
                {
                    "as_of_date": (start + timedelta(days=index)).isoformat(),
                    "close": offset + index,
                    "snapshot_id": f"{instrument}-{index}",
                }
                for index in range(5)
            ]
            self.values[instrument] = (
                bars,
                {"isin": f"INE-{instrument}", "symbol": symbol},
            )

    def histories(self, _start, _end):
        return self.values

    def tracked_instruments(self):
        return [
            {"instrument_id": key, "exchange": "NSE", **identity}
            for key, (_, identity) in self.values.items()
        ]

    def market_history_revisions(self, identifiers):
        return {key: "1" for key in identifiers}

    def universe_snapshot_as_of(self, _index, _date):
        return {"snapshot_id": "snapshot-1"}

    def universe_snapshot_members(self, _snapshot, **_kwargs):
        return [{"isin": "INE-a"}, {"isin": "INE-b"}]


class _Context:
    def __init__(self):
        self.progress = []

    def checkpoint(self, *, progress=None):
        if progress:
            self.progress.append(progress)


class _Runtime:
    def strategy_kind(self, _strategy_id):
        return "factor_score"

    def strategy_ids(self):
        return ("momentum",)

    def revision(self, _strategy_id):
        return {
            "revision_id": "revision-1",
            "definition": {"score": {"factor_modifiers": []}},
        }

    def factor_weights(self, _strategy_id):
        return {"trend": 1.0}

    def factor_multiplier(self, _strategy_id, _factor, _values):
        return 1.0

    def benchmark(self, _strategy_id):
        return None

    def compute_series(self, _strategy_id, bars, _benchmark):
        return {
            bar["as_of_date"]: {
                "factors": {"trend": float(bar["close"])},
                "penalty": 1.0,
                "penalty_reasons": [],
            }
            for bar in bars
        }

    def cross_section(self, _strategy_id, _values):
        return None


class _UnwarmedRuntime(_Runtime):
    def compute_series(self, _strategy_id, _bars, _benchmark):
        return {}

    def cross_section(self, _strategy_id, _values):
        raise AssertionError("empty features must not enter cross-sectional calculation")


def test_bulk_rebuild_calculates_each_stage_and_persists_range(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    research = ResearchJobs(database, _Market(), publisher, _Runtime())
    context = _Context()
    sessions = [f"2025-01-{day:02d}" for day in range(6, 11)]

    result = research.rebuild_range(
        {
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "strategies": ["momentum"],
            "trading_dates": sessions,
        },
        context,
    )

    assert result["execution_model"] == "bulk-staged-vectorized"
    assert result["strategies"]["momentum"]["scored_rows"] == 10
    assert result["weekly_rankings"] == 1
    assert {item["stage"] for item in context.progress} == {
        "loading_market_history",
        "indicators",
        "percentiles",
        "scores",
        "rankings",
    }
    with sqlite_connection(database, read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_daily_scores").fetchone()[0] == 10
        assert (
            connection.execute("SELECT COUNT(*) FROM research_weekly_rankings").fetchone()[0] == 2
        )


def test_bulk_rebuild_accepts_a_range_before_strategy_warmup(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    research = ResearchJobs(database, _Market(), publisher, _UnwarmedRuntime())
    context = _Context()
    sessions = [f"2025-01-{day:02d}" for day in range(6, 11)]

    result = research.rebuild_range(
        {
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "strategies": ["momentum"],
            "trading_dates": sessions,
        },
        context,
    )

    assert result["strategies"]["momentum"]["scored_rows"] == 0
    assert result["weekly_rankings"] == 1
    with sqlite_connection(database, read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_daily_scores").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM research_weekly_rankings").fetchone()[0] == 0
        )


class MarketStub:
    def histories(self, start_date, end_date):
        return {
            key: (
                [
                    {
                        "instrument_id": key,
                        "as_of_date": end_date.isoformat(),
                        "snapshot_id": f"market-{key}",
                    }
                ],
                {"symbol": key, "isin": f"INE-{key}"},
            )
            for key in ("A", "B")
        }


def test_recomputation_removes_stale_daily_and_weekly_members(tmp_path, monkeypatch):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    research = ResearchJobs(database, MarketStub(), publisher)
    include_b = True

    def factors(bars):
        if bars[0]["instrument_id"] == "B" and not include_b:
            return None
        return {
            "factors": {
                key: 50.0 for key in ("trend", "momentum", "efficiency", "volume", "structure")
            },
            "penalty": 1.0,
            "penalty_reasons": [],
        }

    monkeypatch.setitem(
        __import__(
            "src.gates.indicator_implementations", fromlist=["INSTRUMENT_IMPLEMENTATIONS"]
        ).INSTRUMENT_IMPLEMENTATIONS,
        "custom.momentum_quality_features",
        factors,
    )
    day = date(2026, 9, 4)
    research.calculate_day({"as_of_date": day.isoformat(), "strategy_id": "momentum"})
    research.rank_week({"week_end": day.isoformat(), "strategy_id": "momentum"})
    assert len(research.top_rankings(day, 20, "momentum")) == 2

    include_b = False
    research.calculate_day({"as_of_date": day.isoformat(), "strategy_id": "momentum"})
    research.rank_week({"week_end": day.isoformat(), "strategy_id": "momentum"})
    assert [row["symbol"] for row in research.top_rankings(day, 20, "momentum")] == ["A"]


def test_sector_normalized_ranking_is_versioned_and_lineaged(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    features = publisher.publish_json(
        "features/momentum",
        "features-1",
        {
            "snapshot_id": "features-1",
            "as_of_date": "2026-09-10",
            "strategy_id": "momentum",
            "values": {
                "a": {
                    "symbol": "AAA",
                    "factors": {
                        "trend": 1,
                        "momentum": 1,
                        "efficiency": 1,
                        "volume": 1,
                        "structure": 1,
                    },
                },
                "b": {
                    "symbol": "BBB",
                    "factors": {
                        "trend": 2,
                        "momentum": 2,
                        "efficiency": 2,
                        "volume": 2,
                        "structure": 2,
                    },
                },
            },
        },
    )
    sectors = publisher.publish_json(
        "reference/sectors",
        "sectors-1",
        {
            "snapshot_id": "sectors-1",
            "as_of_date": "2026-09-10",
            "values": {"a": "TECH", "b": "TECH"},
        },
    )
    research = ResearchJobs(database, MarketRepository(database), publisher)
    result = research.sector_normalize(
        {
            "as_of_date": "2026-09-10",
            "strategy_id": "momentum",
            "feature_artifact_id": features.artifact_id,
            "sector_artifact_id": sectors.artifact_id,
        }
    )
    assert result["normalization"] == "within_sector_zscore"
    assert result["members"][0]["instrument_id"] == "b"
    manifest, _ = publisher.store.read_json("research/sector-rankings", result["artifact_id"])
    assert set(manifest.upstream_ids) == {"features-1", "sectors-1"}


def test_correlation_readback_clusters_point_in_time_returns(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    start = date(2026, 1, 1)
    market.upsert_instruments(
        [
            TrackedInstrument("a", "IN000000010", "AAA", "NSE", "10", start),
            TrackedInstrument("b", "IN000000011", "BBB", "NSE", "11", start),
        ]
    )
    for offset in range(25):
        day = start + timedelta(days=offset)
        market.upsert_bars(
            "a",
            [
                NormalizedBar(
                    "a",
                    day,
                    Decimal(100 + offset),
                    Decimal(101 + offset),
                    Decimal(99 + offset),
                    Decimal(100 + offset),
                    100,
                )
            ],
            f"a-{offset}",
        )
        market.upsert_bars(
            "b",
            [
                NormalizedBar(
                    "b",
                    day,
                    Decimal(200 + offset * 2),
                    Decimal(202 + offset * 2),
                    Decimal(198 + offset * 2),
                    Decimal(200 + offset * 2),
                    100,
                )
            ],
            f"b-{offset}",
        )
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    result = ResearchJobs(database, market, publisher).correlations(
        {"as_of_date": "2026-01-25", "lookback_sessions": 20, "correlation_threshold": 0.9}
    )
    assert result["clusters"] == [["a", "b"]]
    assert result["matrix"]["a"]["b"] > 0.9
