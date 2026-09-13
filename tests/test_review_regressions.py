import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.application import ArtifactCatalog, ArtifactPublisher, JobStatus, JobStore, JobWorker
from src.application.ingestion import ingest_market_bars
from src.application.operations import sqlite_ready
from src.backtesting import BacktestRunManifest, BacktestStep, FillModelRevision, run
from src.execution_gateway import Ledger, PaperBroker
from src.indicators import IndicatorConfiguration, IndicatorRevision
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore, DomainValidationError, Money, Quantity
from src.portfolio_accounting import Fill, FillSide
from src.portfolio_engine import (
    Candidate,
    Holding,
    MarketBar,
    PortfolioPolicy,
    PortfolioState,
    evaluate,
)
from src.reference_data import InstrumentAlias, resolve_alias
from src.strategies import StrategyRevision, rank_feature_values


def test_cancelled_running_job_cannot_finish_successfully(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    jobs.submit("cancel", "cancel-self")
    worker = JobWorker(
        jobs,
        "worker-a",
        {"cancel-self": lambda payload: (jobs.request_cancel(1), {})[1]},
    )

    assert worker.run_once().status == JobStatus.CANCELLED


def test_stale_job_claim_cannot_complete_after_reclaim(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    jobs.submit("lease", "echo")
    first = jobs.claim_next("worker-a", lease_seconds=1)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE ops_jobs SET lease_until = ? WHERE job_id = ?",
            (datetime(2000, 1, 1, tzinfo=UTC).isoformat(), first.job_id),
        )
        connection.commit()
    second = jobs.claim_next("worker-b")

    assert second.claim_token != first.claim_token
    with pytest.raises(DomainValidationError, match="stale"):
        jobs.complete(first.job_id, {"wrong": True}, first.claim_token)
    assert (
        jobs.complete(second.job_id, {"right": True}, second.claim_token).status
        == JobStatus.SUCCEEDED
    )


def test_expired_claim_cannot_commit_before_reclaim(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    jobs.submit("expired", "echo")
    claimed = jobs.claim_next("worker-a", lease_seconds=1)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE ops_jobs SET lease_until = ? WHERE job_id = ?",
            (datetime(2000, 1, 1, tzinfo=UTC).isoformat(), claimed.job_id),
        )
        connection.commit()
    with pytest.raises(DomainValidationError, match="expired"):
        jobs.complete(claimed.job_id, {}, claimed.claim_token)
    with pytest.raises(DomainValidationError, match="expired"):
        jobs.heartbeat(claimed.job_id, claimed.claim_token)


def test_ledger_rejects_conflicting_idempotency_and_paper_writes_ledger(tmp_path):
    ledger = Ledger(tmp_path / "system.db")
    ledger.open_account("paper", Money("1000"))
    first = Fill("ABC", date(2026, 1, 2), FillSide.BUY, Quantity(1), Money("100"))
    conflicting = Fill("ABC", date(2026, 1, 2), FillSide.BUY, Quantity(2), Money("100"))
    assert ledger.record_fills("paper", "same", 0, (first,)) == 1
    with pytest.raises(DomainValidationError, match="different ledger command"):
        ledger.record_fills("paper", "same", 0, (conflicting,))

    report = PaperBroker(ledger, "paper").submit(
        Fill("XYZ", date(2026, 1, 3), FillSide.BUY, Quantity(1), Money("50")),
        idempotency_key="paper-order-2",
        expected_version=1,
    )
    assert report.ledger_version == 5
    assert ledger.projection("paper").cash == Money("850")


def test_recovery_quarantines_checksum_mismatch(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    catalog = ArtifactCatalog(tmp_path / "system.db")
    store.publish_json("research/test", "broken", {"value": 1})
    (store.root / "research" / "test" / "broken" / "payload.json").write_text(
        '{"value":2}', encoding="utf-8"
    )

    result = ArtifactPublisher(store, catalog).recover()

    assert result["quarantined"] == ("broken",)
    assert not catalog.has("broken")
    assert not store.is_published("research/test", "broken")


def test_store_connections_release_database_file(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    jobs.submit("one")
    jobs.get(1)
    moved = tmp_path / "moved.db"

    database.replace(moved)

    assert moved.is_file()


def test_ranking_ties_are_equal_and_revisions_are_immutable():
    revision = IndicatorRevision("close", "1.0.0", ("close",), ("close",), {}, 1)
    configuration = IndicatorConfiguration.create(revision, "close")
    weights = {"close": Decimal(1)}
    strategy = StrategyRevision(
        "tie-safe",
        uuid4(),
        "1.0.0",
        uuid4(),
        weights,
        (configuration.configuration_id,),
    )
    original_hash = strategy.definition_hash
    weights["close"] = Decimal(0)
    ranking = rank_feature_values(
        date(2026, 1, 2),
        strategy,
        uuid4(),
        {"A": {"close": Decimal(10)}, "B": {"close": Decimal(10)}},
        (uuid4(),),
    )

    assert strategy.definition_hash == original_hash
    assert {member.percentile_values["close"] for member in ranking.members} == {Decimal(50)}
    assert {member.rank for member in ranking.members} == {1}
    with pytest.raises(TypeError, match="immutable"):
        strategy.factor_weights["close"] = Decimal(0)


def test_ingestion_redacts_nested_secrets_and_preserves_raw_response(tmp_path):
    publisher = ArtifactPublisher(
        ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(tmp_path / "system.db")
    )
    bar = NormalizedBar("ABC", date(2026, 1, 2), 10, 12, 9, 11, 5)
    raw, _ = ingest_market_bars(
        publisher,
        "fake",
        (bar,),
        source_request={"api_key": "LEAK", "nested": {"token": "LEAK"}},
        raw_payload={"records": [{"symbol": "ABC", "close": 11}]},
        provider_version="1",
    )
    _, payload = publisher.store.read_json(raw.category, raw.artifact_id)

    assert payload["request"]["api_key"] == "[REDACTED]"
    assert payload["request"]["nested"]["token"] == "[REDACTED]"
    assert payload["response"]["records"][0]["close"] == 11
    assert payload["capture"] == "provider_raw"


def test_secret_redaction_does_not_corrupt_non_secret_session_counts():
    from src.application.security import sanitize_sensitive

    assert sanitize_sensitive({"minimum_valid_sessions": 54, "access_token": "secret"}) == {
        "minimum_valid_sessions": 54,
        "access_token": "[REDACTED]",
    }


def test_missing_database_is_not_ready_or_created(tmp_path):
    missing = tmp_path / "missing.db"

    assert not sqlite_ready(missing)
    assert not missing.exists()


def test_fill_model_changes_execution_and_metrics():
    run_id = uuid4()
    fill_model = FillModelRevision(uuid4(), "1.0.0", slippage_bps=100, fee_bps=100)
    step = BacktestStep(
        date(2026, 1, 2),
        (Candidate("ABC", 90),),
        {"ABC": MarketBar("ABC", date(2026, 1, 2), 100, 110, 99, 105)},
    )
    manifest = BacktestRunManifest(
        run_id,
        ("market-1",),
        uuid4(),
        uuid4(),
        fill_model.revision_id,
        "portfolio-engine-1",
        step.as_of_date,
        step.as_of_date,
        {},
        "abc123",
    )

    result = run(
        PortfolioState(Money("1000")),
        PortfolioPolicy(1, 40, Decimal("0.5")),
        (step,),
        manifest,
        fill_model,
    )

    assert result.fills[0].price == Decimal("101.00")
    assert result.fills[0].fee > 0
    assert result.starting_equity == Decimal(1000)
    assert result.metrics["total_return"] < Decimal("0.05")


def test_prior_close_score_exit_executes_at_next_open_not_current_close():
    state = PortfolioState(
        Money(0),
        (Holding("OLD", Quantity(1), Money(100), Money(50), Decimal(0)),),
    )
    bars = {
        "OLD": MarketBar("OLD", date(2026, 1, 2), 90, 120, 80, 110),
        "NEW": MarketBar("NEW", date(2026, 1, 2), 100, 110, 90, 105),
    }

    decisions, state = evaluate(state, PortfolioPolicy(1, 1, 1), (Candidate("NEW", 100),), bars)

    assert decisions[0].execution_price == Money(90)
    assert all(decision.execution_price != Money(110) for decision in decisions)
    assert state.cash == Money(90)


def test_alias_resolution_is_point_in_time():
    instrument = uuid4()
    old = InstrumentAlias(instrument, "ABC", "NSE", date(2020, 1, 1), date(2022, 12, 31), "1")
    new = InstrumentAlias(instrument, "XYZ", "NSE", date(2023, 1, 1), None, "2")

    assert resolve_alias((old, new), "ABC", "NSE", date(2021, 1, 1)) == old
    with pytest.raises(DomainValidationError, match="exactly one"):
        resolve_alias((old, new), "ABC", "NSE", date(2024, 1, 1))
