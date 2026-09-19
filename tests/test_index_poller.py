from datetime import UTC, datetime, timedelta

from src.application.index_poller import IndexQuotePoller
from src.application.jobs import JobStore


def test_index_poller_persists_disabled_intent_and_interval_lease(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    poller = IndexQuotePoller(database, jobs)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    assert poller.tick(now)["reason"] == "disabled"
    poller.set_enabled(True)
    first = poller.tick(now)
    assert first["submitted"] is True
    second = poller.tick(now + timedelta(seconds=1))
    assert second["reason"] == "interval_not_elapsed"
    assert jobs.get(first["job_id"]).kind == "market.fetch-kite-index-quotes"


def test_index_poller_reconcile_records_provider_success(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    poller = IndexQuotePoller(database, jobs)
    poller.set_enabled(True)
    first = poller.tick(datetime(2026, 9, 13, tzinfo=UTC))
    claimed = jobs.claim_next("quote-worker")
    assert claimed is not None and claimed.job_id == first["job_id"]
    jobs.complete(claimed.job_id, {"quote_count": 2}, claimed.claim_token)
    state = poller.reconcile()
    assert state["last_success"] is not None
    assert state["last_error"] is None


def test_index_poller_records_background_error(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    poller = IndexQuotePoller(database, jobs)

    poller.record_error(RuntimeError("provider unavailable"))

    assert poller.state()["last_error"] == "RuntimeError: provider unavailable"
