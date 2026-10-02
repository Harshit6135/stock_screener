from datetime import date
from types import SimpleNamespace

import pytest

from src.application.catalog import ArtifactCatalog
from src.application.jobs import JobExecutionContext, JobStatus, JobStore
from src.application.market_jobs import NSE_INDEX_SYMBOLS, KiteMarketJobs
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.publication import ArtifactPublisher
from src.application.session_coverage import CompletedSessionCoverage
from src.application.worker import JobWorker
from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError, SqliteArtifactStore

DAY = date(2026, 1, 5)


def setup_market(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    publisher = ArtifactPublisher(SqliteArtifactStore(database), ArtifactCatalog(database))
    return market, publisher


def seed_snapshot(market, snapshot_id, day, instruments):
    market.create_universe_snapshot(snapshot_id=snapshot_id, index_name="NIFTY 500", snapshot_date=day,
        source_url="fixture://nse", raw_csv=snapshot_id.encode(), members=[
            {"isin": isin, "symbol": symbol, "company_name": symbol, "industry": "IT", "series": "BE"}
            for isin, symbol in instruments])


def seed_bars(market, identity, days):
    market.upsert_bars(identity, [NormalizedBar(identity, day, 100, 101, 99, 100, 1) for day in days], "fixture-bars")


def coverage_fixture(tmp_path):
    market, _ = setup_market(tmp_path)
    records = [TrackedInstrument("old", "IN0000000001", "OLD", "NSE", "1", DAY),
               TrackedInstrument("new", "IN0000000002", "NEW", "NSE", "2", DAY),
               TrackedInstrument("unrelated", "IN0000000003", "UNRELATED", "NSE", "3", DAY)]
    records += [TrackedInstrument(symbol, "INDEX:"+symbol, symbol, "NSE", str(i+10), DAY)
                for i, symbol in enumerate(sorted(NSE_INDEX_SYMBOLS))]
    market.upsert_instruments(records)
    seed_snapshot(market, "first", DAY, [("IN0000000001", "OLD")])
    seed_snapshot(market, "second", date(2026, 1, 7), [("IN0000000002", "NEW")])
    # Jan 6 is absent from the observed benchmark calendar; Jan 9 is incomplete.
    sessions = [DAY, date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)]
    for symbol in NSE_INDEX_SYMBOLS:
        seed_bars(market, symbol, sessions)
    seed_bars(market, "old", [DAY, date(2026, 1, 7)])  # Extra exit-only data is not membership.
    seed_bars(market, "new", [date(2026, 1, 7)])
    return market


def test_completed_coverage_uses_membership_and_retains_missing_stock(tmp_path):
    market = coverage_fixture(tmp_path)
    audit = CompletedSessionCoverage(market, lambda: date(2026, 1, 9))
    report = audit.record(DAY, date(2026, 1, 9))
    assert report["observed_session_count"] == 3
    assert report["skipped_incomplete_sessions"] == 1
    assert report["status"] == "PARTIAL"
    assert [(row["instrument_id"], row["missing_session_sample"]) for row in report["missing_bars"]] == [
        ("new", ["2026-01-08"])]
    assert report["missing_bars"][0]["snapshot_id"] == "second"
    assert report["missing_bars"][0]["market_revision"] == market.market_history_revision("new")
    assert report["missing_identities"] == []
    audit.record(DAY, date(2026, 1, 9))
    assert len(market.quality_events(check_type="missing_completed_sessions")) == 1
    assert market.instrument_by_id("new") is not None
    assert market.universe_snapshot_members("second")[0]["symbol"] == "NEW"
    seed_bars(market, "new", [date(2026, 1, 8)])
    assert audit.read(DAY, date(2026, 1, 9))["status"] == "COMPLETE"


def test_calendar_never_uses_unrelated_or_bse_bars_as_session_proof(tmp_path):
    market, _ = setup_market(tmp_path)
    market.upsert_instruments([TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "1", DAY),
                              TrackedInstrument("bse", "INDEX:BSE", "NIFTY 500", "BSE", "2", DAY)])
    seed_snapshot(market, "first", DAY, [("IN0000000001", "STOCK")])
    seed_bars(market, "stock", [DAY])
    seed_bars(market, "bse", [DAY])
    report = CompletedSessionCoverage(market, lambda: date(2026, 1, 9)).read(DAY, DAY)
    assert report["calendar_status"] == "UNAVAILABLE"
    assert report["status"] == "UNAVAILABLE"
    assert report["missing_bars"] == []


def test_coverage_earliest_fallback_and_unresolved_benchmarks(tmp_path):
    market, _ = setup_market(tmp_path)
    market.upsert_instruments([TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "1", DAY),
                              TrackedInstrument("nifty", "INDEX:NIFTY500", "NIFTY 500", "NSE", "2", DAY)])
    seed_snapshot(market, "later", date(2026, 1, 8), [("IN0000000001", "STOCK")])
    seed_bars(market, "nifty", [DAY])
    seed_bars(market, "stock", [DAY])
    report = CompletedSessionCoverage(market, lambda: date(2026, 1, 9)).read(DAY, DAY)
    assert report["membership_lineage"][0]["earliest_fallback"] is True
    assert len(report["missing_identities"]) == 5
    assert report["status"] == "PARTIAL"


def claimed_context(tmp_path, payload=None):
    jobs = JobStore(tmp_path / "jobs.db")
    job = jobs.submit("context-check", "verify", payload or {})
    claimed = jobs.claim_next("worker")
    return jobs, job, JobExecutionContext(jobs, claimed)


def test_progress_context_counter_normalization_and_cursor(tmp_path):
    jobs, job, context = claimed_context(tmp_path, {"account_id": "selected", "strategy_id": "momentum", "revision_id": "rev"})
    context.checkpoint(progress={"stage": "bars", "processed": 2, "total": 4, "job_id": 999})
    progress = [event for event in jobs.events_after(job.job_id) if event["event_type"] == "progress"][-1]
    assert {key: progress["payload"][key] for key in ("current", "total", "percent", "job_id")} == {
        "current": 2, "total": 4, "percent": 50, "job_id": job.job_id}
    assert progress["payload"]["account_id"] == "selected"
    assert progress["payload"]["revision_id"] == "rev"
    context.checkpoint(progress={"stage": "done", "message": "complete"})
    continuation = jobs.events_after(job.job_id, progress["event_id"])
    assert any(event["event_type"] == "progress" for event in continuation)


@pytest.mark.parametrize("progress", [{"current": True}, {"current": float("nan")}, {"total": -1},
                                      {"percent": float("inf")}, {"stage": None}, {"message": 123}])
def test_invalid_progress_cannot_publish_unreadable_events(tmp_path, progress):
    jobs, job, context = claimed_context(tmp_path)
    with pytest.raises(DomainValidationError, match="progress"):
        context.checkpoint(progress=progress)
    assert not any(event["event_type"] == "progress" for event in jobs.events_after(job.job_id))


def test_cancelled_checkpoint_emits_no_later_progress(tmp_path):
    jobs, job, context = claimed_context(tmp_path)
    jobs.request_cancel(job.job_id)
    with pytest.raises(DomainValidationError, match="cancellation"):
        context.checkpoint(progress={"stage": "finished"})
    assert jobs.get(job.job_id).status == JobStatus.CANCELLED
    assert not any(event["event_type"] == "progress" for event in jobs.events_after(job.job_id))


def test_bulk_progress_covers_error_empty_cached_and_fetched_paths(tmp_path, monkeypatch):
    market, publisher = setup_market(tmp_path)
    symbols = ["ERR", "EMPTY", "CACHED", "FETCH"]
    market.upsert_instruments([TrackedInstrument(symbol, f"IN{i:010d}", symbol, "NSE", str(i+1), DAY)
                              for i, symbol in enumerate(symbols)])
    seed_snapshot(market, "bulk-members", DAY, [(f"IN{i:010d}", symbol)
                                               for i, symbol in enumerate(symbols)])
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
    monkeypatch.setattr("src.application.providers._ProviderThrottle.wait", lambda self: None)
    result = jobs.fetch_bulk_bars({"start_date": DAY.isoformat(), "end_date": DAY.isoformat(),
        "items": [{"symbol": symbol} for symbol in symbols]}, SimpleNamespace(checkpoint=lambda **kwargs: progress.append(kwargs["progress"])))
    assert {row["status"] for row in result["results"]} == {"error", "empty", "skipped", "fetched"}
    assert result["failed"] == 1
    assert "DO_NOT_PERSIST" not in str(result)
    assert 3 not in calls
    assert {event["current"] for event in progress} >= {0, 1, 2, 3, 4}


def test_bulk_cancellation_bounds_pending_provider_work(tmp_path, monkeypatch):
    market, publisher = setup_market(tmp_path)
    symbols = [f"STOCK{i}" for i in range(40)]
    market.upsert_instruments([TrackedInstrument(symbol, f"IN{i:010d}", symbol, "NSE", str(i+1), DAY)
                              for i, symbol in enumerate(symbols)])
    seed_snapshot(market, "bulk-members", DAY, [(f"IN{i:010d}", symbol)
                                               for i, symbol in enumerate(symbols)])
    calls = []

    class Client:
        def historical_data(self, token, start, end, interval):
            calls.append(token)
            return [{"date": DAY, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}]

    market_jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token")
    monkeypatch.setattr(market_jobs, "_client", Client)
    monkeypatch.setattr("src.application.providers._ProviderThrottle.wait", lambda self: None)
    store = JobStore(market.path)
    submitted = store.submit("cancel-bulk", "market.bulk", {"start_date": DAY.isoformat(), "end_date": DAY.isoformat(),
        "items": [{"symbol": symbol} for symbol in symbols]})

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
    assert not any(event["event_type"] == "progress" and event["event_id"] > cancelled for event in events)



@pytest.mark.parametrize("defect", ["missing_volume", "fractional_volume", "boolean_volume", "duplicate", "outside_range", "bad_date", "bad_ohlc"])
def test_malformed_historical_provider_payload_is_rejected_before_publication(tmp_path, monkeypatch, defect):
    market, publisher = setup_market(tmp_path)
    market.upsert_instruments([TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "42", DAY)])
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
    monkeypatch.setattr(jobs, "_client", lambda: SimpleNamespace(historical_data=lambda *args, **kwargs: records))
    with pytest.raises(DomainValidationError):
        jobs.fetch_bars({"symbol": "STOCK", "start_date": DAY.isoformat(), "end_date": DAY.isoformat()})
    assert market.bars("stock", DAY, DAY) == []
    assert not market.has_coverage("stock", DAY, DAY, "kite")
    assert publisher.catalog.artifacts() == ()
    assert market.market_history_revision("stock") == "0"



def test_manual_preparation_runs_quality_before_indicators_and_reuses_history(tmp_path, monkeypatch):
    from src.application.market_refresh import MarketRefreshPlanner
    from src.application.pipeline_preparation import PipelinePreparation

    market, publisher = setup_market(tmp_path)
    seed_snapshot(market, "pinned", DAY, [("IN0000000001", "STOCK")])
    records = [TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "1", DAY)]
    records += [TrackedInstrument(symbol, "INDEX:"+symbol, symbol, "NSE", str(i+10), DAY)
                for i, symbol in enumerate(sorted(NSE_INDEX_SYMBOLS))]
    records.append(TrackedInstrument("obsolete-index", "INDEX:OBSOLETE", "OBSOLETE", "NSE", "999", DAY))
    market.upsert_instruments(records)
    provider_calls, stages = [], []

    class Client:
        def historical_data(self, token, start, end, interval):
            provider_calls.append((token, start, end))
            if token == 1 or not start <= DAY <= end:
                return []
            return [{"date": DAY, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 0}]

    market_jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token")
    monkeypatch.setattr(market_jobs, "_client", Client)
    monkeypatch.setattr(market_jobs, "sync_snapshot_instruments", lambda payload, context: {"unresolved": []})
    monkeypatch.setattr("src.application.providers._ProviderThrottle.wait", lambda self: None)
    universe = SimpleNamespace(download_nifty500_constituents=lambda payload, context: {"snapshot_id": "pinned", "reused": True})
    corporate = SimpleNamespace(detect_job=lambda payload, context: {},
        process_actionable=lambda history, context: {})

    def indicators(payload, context):
        assert market.quality_events(check_type="missing_completed_sessions")
        return {"rebuilt": 0}

    refresh = MarketRefreshPlanner(market.path, market, JobStore(market.path), publisher)
    preparation = PipelinePreparation(universe, market, market_jobs, corporate,
                                      SimpleNamespace(rebuild_indicators=indicators), refresh, None)
    context = SimpleNamespace(checkpoint=lambda **kwargs: stages.append(kwargs["progress"]["stage"]))
    first = preparation.run({"start_date": DAY.isoformat(), "end_date": DAY.isoformat()}, context)
    assert first["quality"]["missing_bars"][0]["instrument_id"] == "stock"
    assert all(token != "999" for token, _, _ in provider_calls)
    assert stages.index("quality") > max(i for i, stage in enumerate(stages) if stage == "market_history")
    assert stages.index("quality") < stages.index("indicators")
    assert first["reconciliation"]["session_coverage"] == first["quality"]
    first_call_count = len(provider_calls)
    second = preparation.run({"start_date": DAY.isoformat(), "end_date": DAY.isoformat()}, context)
    assert len(provider_calls) == first_call_count
    assert second["quality"] == first["quality"]
    assert len(market.quality_events(check_type="missing_completed_sessions")) == 1



def test_quality_warning_does_not_remove_stock_from_research(tmp_path):
    from datetime import timedelta

    from src.application.research_jobs import ResearchJobs

    market, publisher = setup_market(tmp_path)
    instruments = [TrackedInstrument("a", "IN0000000001", "AAA", "NSE", "1", DAY),
                   TrackedInstrument("b", "IN0000000002", "BBB", "NSE", "2", DAY)]
    market.upsert_instruments(instruments)
    seed_snapshot(market, "research", DAY, [("IN0000000001", "AAA"), ("IN0000000002", "BBB")])
    dates = [DAY + timedelta(days=i) for i in range(5)]
    for instrument in instruments:
        prices = [100, 130, 131, 132, 133] if instrument.instrument_id == "a" else [100, 101, 102, 103, 104]
        market.upsert_bars(instrument.instrument_id,
            [NormalizedBar(instrument.instrument_id, day, price, price, price, price, 10)
             for day, price in zip(dates, prices)], "rank-bars")
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
        def benchmark(self, strategy):
            return None
        def compute_series(self, strategy, bars, benchmark):
            return {bar["as_of_date"]: {"factors": {"trend": float(bar["close"])},
                                            "penalty": 1.0, "penalty_reasons": []} for bar in bars}
        def cross_section(self, strategy, values):
            return None

    research = ResearchJobs(market.path, market, publisher, Runtime())
    result = research.rebuild_range({"start_date": DAY.isoformat(),
        "end_date": dates[-1].isoformat(), "strategies": ["momentum"],
        "trading_dates": [day.isoformat() for day in dates]},
        SimpleNamespace(checkpoint=lambda **kwargs: None))
    assert result["strategies"]["momentum"]["scored_rows"] == 10
    assert market.instrument_by_id("a") is not None


def test_terminal_progress_sse_reconnect_honors_cursor(tmp_path):
    from flask import Flask

    from src.application.web import create_operations_blueprint

    store = JobStore(tmp_path / "jobs.db")
    job = store.submit("cursor", "echo", {})
    claimed = store.claim_next("worker")
    context = JobExecutionContext(store, claimed)
    context.checkpoint(progress={"stage": "first", "current": 1, "total": 2})
    first = [event for event in store.events_after(job.job_id) if event["event_type"] == "progress"][-1]
    context.checkpoint(progress={"stage": "second", "current": 2, "total": 2})
    store.complete(job.job_id, {}, claimed.claim_token)
    app = Flask(__name__)
    app.register_blueprint(create_operations_blueprint(store))
    client = app.test_client()
    response = client.get(f"/api/v2/operations/jobs/{job.job_id}/events",
                          headers={"Accept": "text/event-stream", "Last-Event-ID": str(first["event_id"])})
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "event: job-event" in body
    assert '"stage": "second"' in body
    assert '"stage": "first"' not in body
    assert "event: terminal" in body
