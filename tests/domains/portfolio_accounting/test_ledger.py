from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.domains.portfolio_accounting.api import OpeningPosition
from src.platform_kernel import DomainValidationError, Money, Quantity


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


def test_ledger_rejects_conflicting_idempotency_and_records_manual_fills(tmp_path):
    ledger = Ledger(tmp_path / "system.db")
    ledger.open_account("paper", Money("1000"))
    first = Fill("ABC", date(2026, 1, 2), FillSide.BUY, Quantity(1), Money("100"))
    conflicting = Fill("ABC", date(2026, 1, 2), FillSide.BUY, Quantity(2), Money("100"))
    assert ledger.record_fills("paper", "same", 0, (first,)) == 1
    with pytest.raises(DomainValidationError, match="different ledger command"):
        ledger.record_fills("paper", "same", 0, (conflicting,))

    assert (
        ledger.record_fills(
            "paper",
            "manual-order-2",
            1,
            (Fill("XYZ", date(2026, 1, 3), FillSide.BUY, Quantity(1), Money("50")),),
        )
        == 2
    )
    assert ledger.projection("paper").cash == Money("850")


def test_ledger_import_opening_positions(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    ledger.open_account("acc1", Money(Decimal(10000), "INR"))

    op = OpeningPosition(
        "inst1",
        date(2026, 1, 1),
        Quantity(100),
        Money(Decimal(50), "INR"),
        datetime(2026, 9, 10, tzinfo=UTC),
        "broker_snapshot",
    )
    ledger.import_opening_positions("acc1", "idem_1", 0, [op])

    proj = ledger.projection("acc1")
    assert proj.cash.amount == Decimal(10000)
    assert len(proj.open_lots) == 1
    assert proj.open_lots[0].remaining_units.units == 100

    journal = ledger.journal("acc1")
    assert len(journal) == 0  # Imported positions only appear as buys once closed

    # Sell 50
    sell = Fill(
        "inst1",
        date(2026, 9, 11),
        FillSide.SELL,
        Quantity(50),
        Money(Decimal(60), "INR"),
        executed_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
    )
    ledger.record_fills("acc1", "idem_2", 1, [sell])

    journal = ledger.journal("acc1")
    assert len(journal) == 1
    assert journal[0]["units"] == 50
    assert journal[0]["realised_pnl"] == "500"
