from datetime import date

from src.domains.portfolio_engine import PortfolioProposalStore
from src.platform_kernel.sqlite import sqlite_connection


def _insert(store: PortfolioProposalStore) -> None:
    store.insert_pending(
        proposal_id="proposal-1",
        account_id="account-1",
        strategy_id="manual",
        action_date="2026-09-01",
        ranking_week_end="2026-09-01",
        expected_ledger_version=3,
        artifact_id="proposal-1",
        decisions=[{"type": "BUY", "instrument_id": "instrument-1"}],
        timestamp="2026-09-01T10:00:00+00:00",
        event_type="GENERATED_MANUAL",
        event_detail={"reason": "rebalance"},
    )


def test_proposal_store_owns_lifecycle_projection_and_events(tmp_path):
    store = PortfolioProposalStore(tmp_path / "system.db")
    _insert(store)

    proposal = store.get("proposal-1")
    assert proposal["status"] == "PENDING"
    assert proposal["decisions"] == [{"type": "BUY", "instrument_id": "instrument-1"}]
    assert store.list_for_account("account-1", action_date=date(2026, 9, 1)) == [proposal]
    assert store.action_dates("account-1") == [date(2026, 9, 1)]
    assert store.events("proposal-1")[0]["detail"] == {"reason": "rebalance"}


def test_projection_recovery_is_idempotent_and_status_event_atomic(tmp_path):
    store = PortfolioProposalStore(tmp_path / "system.db")
    values = {
        "proposal_id": "proposal-2",
        "account_id": "account-2",
        "strategy_id": "manual",
        "action_date": "2026-09-02",
        "ranking_week_end": "2026-09-02",
        "expected_ledger_version": 4,
        "artifact_id": "proposal-2",
        "decisions": [],
        "timestamp": "2026-09-02T10:00:00+00:00",
        "event_type": "GENERATED_MANUAL",
    }
    store.recover_pending(**values)
    store.recover_pending(**values)
    assert [event["event_type"] for event in store.events("proposal-2")] == ["GENERATED_MANUAL"]

    store.transition_pending("proposal-2", "APPROVED", "2026-09-02T10:01:00+00:00")
    with sqlite_connection(store.database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        assert store.mark_processed(connection, "proposal-2", 5, "2026-09-02T10:02:00+00:00", [])
    assert store.get("proposal-2")["status"] == "PROCESSED"
    assert [event["event_type"] for event in store.events("proposal-2")] == [
        "GENERATED_MANUAL",
        "APPROVED",
        "PROCESSED",
    ]
