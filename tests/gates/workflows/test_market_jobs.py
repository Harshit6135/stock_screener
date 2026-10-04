from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.market_data import NSE_INDEX_SYMBOLS
from src.domains.operations import JobStatus, JobStore, JobWorker
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.market_jobs import PHASE2_BENCHMARK_SYMBOLS, KiteMarketJobs
from src.gates.workflows.market_refresh import MarketRefreshPlanner
from src.platform_kernel import ArtifactStore, DomainValidationError, SqliteArtifactStore

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


def test_empty_prelisting_kite_range_is_successful_and_not_refetched(tmp_path, monkeypatch):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    market.upsert_instruments(
        [TrackedInstrument("new-ipo", "IN0000000001", "NEWIPO", "NSE", "42", date(2026, 1, 1))]
    )
    market.create_universe_snapshot(
        snapshot_id="current-member",
        index_name="NIFTY 500",
        snapshot_date=date(2026, 1, 1),
        source_url="fixture://nse",
        raw_csv=b"NEWIPO",
        members=[
            {
                "isin": "IN0000000001",
                "symbol": "NEWIPO",
                "company_name": "NEWIPO",
                "industry": "IT",
                "series": "EQ",
            }
        ],
    )
    jobs = KiteMarketJobs(
        market,
        ArtifactPublisher(SqliteArtifactStore(database), ArtifactCatalog(database)),
        None,
        tmp_path / "token.txt",
    )

    class EmptyHistoryClient:
        def historical_data(self, token, start, end, interval):
            return []

    monkeypatch.setattr(jobs, "_client", lambda: EmptyHistoryClient())
    payload = {
        "symbol": "NEWIPO",
        "exchange": "NSE",
        "start_date": "2015-01-01",
        "end_date": "2015-12-31",
    }

    first = jobs.fetch_bars(payload)
    second = jobs.fetch_bars(payload)

    assert first["bar_count"] == 0
    assert first["skipped"] is False
    assert second["skipped"] is True


def test_bulk_progress_covers_error_empty_cached_and_fetched_paths(tmp_path, monkeypatch):
    market, publisher = setup_market(tmp_path)
    symbols = ["ERR", "EMPTY", "CACHED", "FETCH"]
    market.upsert_instruments(
        [
            TrackedInstrument(symbol, f"IN{i:010d}", symbol, "NSE", str(i + 1), DAY)
            for i, symbol in enumerate(symbols)
        ]
    )
    seed_snapshot(
        market, "bulk-members", DAY, [(f"IN{i:010d}", symbol) for i, symbol in enumerate(symbols)]
    )
    market.record_fetch_coverage("CACHED", DAY, DAY, provider="kite", bar_count=0)
    calls, progress = [], []

    class Client:
        def historical_data(self, token, start, end, interval):
            calls.append(token)
            if token == 1:
                raise DomainValidationError("access_token=DO_NOT_PERSIST invalid session")
            if token == 2:
                return []
            return [{"date": DAY, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}]

    jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token")
    monkeypatch.setattr(jobs, "_client", Client)
    monkeypatch.setattr(
        "src.domains.market_data.providers._ProviderThrottle.wait", lambda self: None
    )
    result = jobs.fetch_bulk_bars(
        {
            "start_date": DAY.isoformat(),
            "end_date": DAY.isoformat(),
            "items": [{"symbol": symbol} for symbol in symbols],
        },
        SimpleNamespace(checkpoint=lambda **kwargs: progress.append(kwargs["progress"])),
    )
    assert {row["status"] for row in result["results"]} == {"error", "empty", "skipped", "fetched"}
    assert result["failed"] == 1
    assert "DO_NOT_PERSIST" not in str(result)
    assert 3 not in calls
    assert {event["current"] for event in progress} >= {0, 1, 2, 3, 4}


def test_bulk_cancellation_bounds_pending_provider_work(tmp_path, monkeypatch):
    market, publisher = setup_market(tmp_path)
    symbols = [f"STOCK{i}" for i in range(40)]
    market.upsert_instruments(
        [
            TrackedInstrument(symbol, f"IN{i:010d}", symbol, "NSE", str(i + 1), DAY)
            for i, symbol in enumerate(symbols)
        ]
    )
    seed_snapshot(
        market, "bulk-members", DAY, [(f"IN{i:010d}", symbol) for i, symbol in enumerate(symbols)]
    )
    calls = []

    class Client:
        def historical_data(self, token, start, end, interval):
            calls.append(token)
            return [{"date": DAY, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}]

    market_jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token")
    monkeypatch.setattr(market_jobs, "_client", Client)
    monkeypatch.setattr(
        "src.domains.market_data.providers._ProviderThrottle.wait", lambda self: None
    )
    store = JobStore(market.path)
    submitted = store.submit(
        "cancel-bulk",
        "market.bulk",
        {
            "start_date": DAY.isoformat(),
            "end_date": DAY.isoformat(),
            "items": [{"symbol": symbol} for symbol in symbols],
        },
    )

    def handler(payload, context):
        def checkpoint(*, progress):
            if progress["current"] == 3:
                store.request_cancel(submitted.job_id)
            return context.checkpoint(progress=progress)

        return market_jobs.fetch_bulk_bars(payload, SimpleNamespace(checkpoint=checkpoint))

    result = JobWorker(store, "worker", {"market.bulk": handler}).run_once()
    assert result.status == JobStatus.CANCELLED
    assert len(calls) <= 3 + 10  # Three committed results plus at most ten outstanding reads.
    assert sum(row["bar_count"] for row in market.coverage()) == 3
    events = store.events_after(submitted.job_id)
    cancelled = next(event["event_id"] for event in events if event["event_type"] == "cancelled")
    assert not any(
        event["event_type"] == "progress" and event["event_id"] > cancelled for event in events
    )


@pytest.mark.parametrize(
    "defect",
    [
        "missing_volume",
        "fractional_volume",
        "boolean_volume",
        "duplicate",
        "outside_range",
        "bad_date",
        "bad_ohlc",
    ],
)
def test_malformed_historical_provider_payload_is_rejected_before_publication(
    tmp_path, monkeypatch, defect
):
    market, publisher = setup_market(tmp_path)
    market.upsert_instruments(
        [TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "42", DAY)]
    )
    seed_snapshot(market, "malformed-member", DAY, [("IN0000000001", "STOCK")])
    row = {"date": DAY, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
    records = [row]
    if defect == "missing_volume":
        del row["volume"]
    elif defect == "fractional_volume":
        row["volume"] = 1.5
    elif defect == "boolean_volume":
        row["volume"] = True
    elif defect == "duplicate":
        records.append(dict(row))
    elif defect == "outside_range":
        row["date"] = date(2026, 1, 6)
    elif defect == "bad_date":
        row["date"] = "not-a-date"
    elif defect == "bad_ohlc":
        row["high"] = 90
    jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token")
    monkeypatch.setattr(
        jobs, "_client", lambda: SimpleNamespace(historical_data=lambda *args, **kwargs: records)
    )
    with pytest.raises(DomainValidationError):
        jobs.fetch_bars(
            {"symbol": "STOCK", "start_date": DAY.isoformat(), "end_date": DAY.isoformat()}
        )
    assert market.bars("stock", DAY, DAY) == []
    assert not market.has_coverage("stock", DAY, DAY, "kite")
    assert publisher.catalog.artifacts() == ()
    assert market.market_history_revision("stock") == "0"


class TestBenchmarkSet:
    def test_six_benchmarks_are_defined(self):
        expected = {
            "NIFTY 50",
            "NIFTY 500",
            "NIFTY NEXT 50",
            "NIFTY MIDCAP 150",
            "NIFTY SMLCAP 250",
            "INDIA VIX",
        }
        assert NSE_INDEX_SYMBOLS == expected
        assert PHASE2_BENCHMARK_SYMBOLS == expected


class TestUnsupportedExchange:
    def test_direct_and_bulk_unsupported_exchange_requests_fail_before_provider_access(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        publisher = ArtifactPublisher(
            ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(tmp_path / "system.db")
        )
        jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token.txt")
        with pytest.raises(DomainValidationError, match="bar fetch requires"):
            jobs.fetch_bars(
                {
                    "symbol": "OLD",
                    "exchange": "OTHER",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-01",
                }
            )
        with pytest.raises(DomainValidationError, match="supported exchange"):
            jobs.fetch_bulk_bars(
                {
                    "items": [{"symbol": "OLD", "exchange": "OTHER"}],
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-01",
                },
                None,
            )


class TestSnapshotInstrumentSync:
    def test_sync_snapshot_instruments_resolves_members_and_benchmarks(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        catalog = ArtifactCatalog(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), catalog)
        snap_id = str(uuid4())
        observed = date(2026, 1, 1)
        market.create_universe_snapshot(
            snapshot_id=snap_id,
            index_name="NIFTY 500",
            snapshot_date=observed,
            source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,RELIANCE,Reliance,Energy,EQ",
            members=[
                {
                    "isin": "IN0000000001",
                    "symbol": "RELIANCE",
                    "company_name": "Reliance",
                    "industry": "Energy",
                    "series": "EQ",
                }
            ],
        )
        # Mock the Kite NSE dump
        fake_kite_dump = [
            {"tradingsymbol": "RELIANCE", "instrument_token": "256265", "instrument_type": "EQ"},
            {"tradingsymbol": "NIFTY 50", "instrument_token": "256000", "instrument_type": "INDEX"},
            {
                "tradingsymbol": "NIFTY 500",
                "instrument_token": "256001",
                "instrument_type": "INDEX",
            },
            {
                "tradingsymbol": "NIFTY NEXT 50",
                "instrument_token": "256002",
                "instrument_type": "INDEX",
            },
            {
                "tradingsymbol": "NIFTY MIDCAP 150",
                "instrument_token": "256003",
                "instrument_type": "INDEX",
            },
            {
                "tradingsymbol": "NIFTY SMLCAP 250",
                "instrument_token": "256004",
                "instrument_type": "INDEX",
            },
            {
                "tradingsymbol": "INDIA VIX",
                "instrument_token": "256005",
                "instrument_type": "INDEX",
            },
        ]
        token_path = tmp_path / "token.txt"
        token_path.write_text("dummy_token")
        jobs = KiteMarketJobs(
            market,
            publisher,
            None,
            token_path,
        )
        jobs._kite_dump_cache = {datetime.now(UTC).date().isoformat(): fake_kite_dump}
        result = jobs.sync_snapshot_instruments({"snapshot_id": snap_id})
        assert result["resolved_count"] == 7  # 1 member + 6 benchmarks
        assert result["unresolved"] == []
        # Verify instruments are persisted
        instruments = market.instruments(symbol="RELIANCE", limit=1)
        assert len(instruments) == 1
        assert instruments[0]["provider_token"] == "256265"

    def test_sync_snapshot_instruments_reports_unresolved(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        catalog = ArtifactCatalog(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), catalog)
        snap_id = str(uuid4())
        observed = date(2026, 1, 1)
        market.create_universe_snapshot(
            snapshot_id=snap_id,
            index_name="NIFTY 500",
            snapshot_date=observed,
            source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000099,GHOSTSYM,Ghost,IT,EQ",
            members=[
                {
                    "isin": "IN0000000099",
                    "symbol": "GHOSTSYM",
                    "company_name": "Ghost",
                    "industry": "IT",
                    "series": "EQ",
                }
            ],
        )
        # Kite dump without GHOSTSYM
        fake_kite_dump = [
            {"tradingsymbol": "NIFTY 50", "instrument_token": "256000", "instrument_type": "INDEX"},
            {
                "tradingsymbol": "NIFTY 500",
                "instrument_token": "256001",
                "instrument_type": "INDEX",
            },
            {
                "tradingsymbol": "NIFTY NEXT 50",
                "instrument_token": "256002",
                "instrument_type": "INDEX",
            },
            {
                "tradingsymbol": "NIFTY MIDCAP 150",
                "instrument_token": "256003",
                "instrument_type": "INDEX",
            },
            {
                "tradingsymbol": "NIFTY SMLCAP 250",
                "instrument_token": "256004",
                "instrument_type": "INDEX",
            },
            {
                "tradingsymbol": "INDIA VIX",
                "instrument_token": "256005",
                "instrument_type": "INDEX",
            },
        ]
        token_path = tmp_path / "token.txt"
        token_path.write_text("dummy_token")
        jobs = KiteMarketJobs(
            market,
            publisher,
            None,
            token_path,
        )
        jobs._kite_dump_cache = {datetime.now(UTC).date().isoformat(): fake_kite_dump}
        result = jobs.sync_snapshot_instruments({"snapshot_id": snap_id})
        assert result["resolved_count"] == 6  # only benchmarks, not GHOSTSYM
        assert len(result["unresolved"]) == 1
        assert result["unresolved"][0]["symbol"] == "GHOSTSYM"


def test_history_fetch_requires_current_membership_or_exact_exit_session(tmp_path, monkeypatch):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    first = date(2026, 6, 1)
    decision = date(2026, 6, 2)
    target = date(2026, 6, 3)
    market.upsert_instruments(
        [
            TrackedInstrument("removed", "IN0000000001", "REMOVED", "NSE", "11", first),
            TrackedInstrument("current", "IN0000000002", "CURRENT", "NSE", "12", first),
        ]
    )
    market.create_universe_snapshot(
        snapshot_id="before",
        index_name="NIFTY 500",
        snapshot_date=first,
        source_url="fixture://nse",
        raw_csv=b"before",
        members=[
            {
                "isin": "IN0000000001",
                "symbol": "REMOVED",
                "company_name": "Removed",
                "industry": "IT",
                "series": "EQ",
            }
        ],
    )
    market.create_universe_snapshot(
        snapshot_id="decision",
        index_name="NIFTY 500",
        snapshot_date=decision,
        source_url="fixture://nse",
        raw_csv=b"after",
        members=[
            {
                "isin": "IN0000000002",
                "symbol": "CURRENT",
                "company_name": "Current",
                "industry": "IT",
                "series": "EQ",
            }
        ],
    )
    market.record_exit_eligibility(
        instrument_id="removed",
        isin="IN0000000001",
        symbol="REMOVED",
        decision_date=decision,
        decision_snapshot_id="decision",
        target_session_date=target,
    )
    queue = JobStore(database)
    planner = MarketRefreshPlanner(database, market, queue)
    planned = planner.schedule({"start_date": first.isoformat(), "end_date": first.isoformat()})
    queued_symbols = {
        item["symbol"]
        for job_id in planned["job_ids"]
        for item in queue.get(job_id).payload.get("items", [])
    }
    assert "CURRENT" in queued_symbols
    assert "REMOVED" not in queued_symbols
    jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token.txt")
    calls = []

    class Client:
        def historical_data(self, token, start, end, interval):
            calls.append((token, start, end))
            return [
                {"date": target, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10}
            ]

    monkeypatch.setattr(jobs, "_client", Client)
    monkeypatch.setattr(
        "src.domains.market_data.providers._ProviderThrottle.wait", lambda self: None
    )
    payload = {
        "symbol": "REMOVED",
        "exchange": "NSE",
        "start_date": target.isoformat(),
        "end_date": target.isoformat(),
    }
    with pytest.raises(DomainValidationError, match="outside the current"):
        jobs.fetch_bars(payload)
    with pytest.raises(DomainValidationError, match="outside the current"):
        jobs.fetch_bulk_bars(
            {
                "items": [{"symbol": "REMOVED"}],
                "start_date": target.isoformat(),
                "end_date": target.isoformat(),
            },
            None,
        )
    assert calls == []
    fetched = jobs.fetch_bars({**payload, "exit_only": True})
    assert fetched["bar_count"] == 1
    assert len(calls) == 1
    assert market.has_coverage("removed", target, target, "kite", coverage_context="exit_only")
    assert not market.has_coverage("removed", target, target, "kite")
    assert jobs.fetch_bars({**payload, "exit_only": True})["skipped"] is True
    with pytest.raises(DomainValidationError, match="exit-only"):
        jobs.fetch_bars({**payload, "start_date": decision.isoformat(), "exit_only": True})
