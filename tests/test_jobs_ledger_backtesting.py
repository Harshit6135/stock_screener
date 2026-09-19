from datetime import date
from decimal import Decimal

import pytest

from src.application import JobStatus, JobStore
from src.backtesting import BacktestStep, run
from src.execution_gateway import Ledger
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.portfolio_accounting import Fill, FillSide
from src.portfolio_engine import Candidate, MarketBar, PortfolioPolicy, PortfolioState


def test_jobs_are_idempotent_and_events_are_cursor_readable(tmp_path):
    jobs = JobStore(tmp_path / "ops.db")
    first = jobs.submit("same-inputs")
    assert jobs.submit("same-inputs") == first
    claim = jobs.claim_next("test-worker")
    assert claim.status == JobStatus.RUNNING
    jobs.emit(first.job_id, "progress", {"percent": 50})
    assert [event["event_type"] for event in jobs.events_after(first.job_id)] == [
        "submitted",
        "claimed",
        "progress",
    ]
    with pytest.raises(DomainValidationError, match="require a claim"):
        jobs.transition(first.job_id, JobStatus.QUEUED)


def test_ledger_is_idempotent_versioned_and_rebuilds_projection(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    ledger.open_account("paper", Money("1000"))
    fill = Fill("ABC", date(2026, 1, 2), FillSide.BUY, Quantity(2), Money("100"))
    assert ledger.record_fills("paper", "command-1", 0, [fill]) == 1
    assert ledger.record_fills("paper", "command-1", 0, [fill]) == 1
    assert ledger.projection("paper").cash == Money("800")
    with pytest.raises(DomainValidationError, match="stale"):
        ledger.record_fills("paper", "command-2", 0, [fill])


def test_ledger_rejects_invalid_fills_before_appending_events(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    ledger.open_account("paper", Money("1000"))
    buy = Fill("ABC", date(2026, 1, 2), FillSide.BUY, Quantity(2), Money("100"))
    assert ledger.record_fills("paper", "buy", 0, [buy]) == 1
    with pytest.raises(DomainValidationError, match="confirmed cash"):
        ledger.record_fills(
            "paper",
            "overdraft",
            1,
            [Fill("XYZ", date(2026, 1, 3), FillSide.BUY, Quantity(9), Money("100"))],
        )
    with pytest.raises(DomainValidationError, match="held units"):
        ledger.record_fills(
            "paper",
            "oversell",
            1,
            [Fill("ABC", date(2026, 1, 3), FillSide.SELL, Quantity(3), Money("100"))],
        )
    assert ledger.projection("paper").cash == Money("800")
    assert (
        ledger.record_fills(
            "paper",
            "valid-sell",
            1,
            [Fill("ABC", date(2026, 1, 3), FillSide.SELL, Quantity(2), Money("110"))],
        )
        == 2
    )


def test_in_memory_backtest_uses_pure_engine_and_publishes_no_shared_database():
    bar = MarketBar("ABC", date(2026, 1, 2), Decimal(100), Decimal(110), Decimal(99), Decimal(105))
    result = run(
        PortfolioState(Money("1000")),
        PortfolioPolicy(1, Decimal(40), Decimal(1)),
        (BacktestStep(date(2026, 1, 2), (Candidate("ABC", Decimal(90)),), {"ABC": bar}),),
    )
    assert result.final_state.holdings[0].instrument_id == "ABC"
    assert result.equity_curve[0][1] == Decimal(1050)
