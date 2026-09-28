from datetime import date, datetime, UTC
from decimal import Decimal

import pytest

from src.execution_gateway.ledger import Ledger
from src.platform_kernel import Money, Quantity
from src.portfolio_accounting.api import OpeningPosition
from src.application.portfolio_performance import PortfolioPerformance

def test_calculate_xirr(tmp_path):
    ledger = Ledger(tmp_path / "system.db")
    perf = PortfolioPerformance(ledger)
    
    # Create account and add some cash
    ledger.open_account("acct1", Money(Decimal("0")))
    
    ledger.record_cash_transfer(
        account_id="acct1",
        idempotency_key="idemp_cash_1",
        expected_version=0,
        direction="DEPOSIT",
        amount=Money(Decimal("100000")),
        occurred_at=datetime(2021, 1, 1, tzinfo=UTC),
    )
    
    # Create an imported position (cost basis)
    import uuid
    ledger.import_opening_positions(
        account_id="acct1",
        idempotency_key="idemp_import_1",
        expected_version=1,
        positions=[
            OpeningPosition(
                instrument_id="RELIANCE",
                acquisition_date=date(2021, 1, 1),
                imported_at=datetime(2021, 1, 1, 10, 0, tzinfo=UTC),
                units=Quantity(100),
                unit_cost=Money(Decimal("2000")),
                broker_provenance="IMPORT",
            )
        ]
    )
    # The cost basis is 200,000. So total external flow from investor is 100,000 (initial cash) + 200,000 (imported stock cost) = 300,000.
    
    # Calculate XIRR with current equity = 400,000 at 2022-01-01
    xirr = perf.calculate_xirr("acct1", Decimal("400000"), date(2022, 1, 1))
    
    assert xirr is not None
    assert xirr > Decimal("0")
