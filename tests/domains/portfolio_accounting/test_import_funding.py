import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.domains.portfolio_accounting import (
    Fill,
    FillSide,
    Ledger,
    OpeningPosition,
    PortfolioPerformance,
)
from src.platform_kernel import DomainValidationError, Money, Quantity


def test_legacy_import_cost_is_debited_once_and_deficit_is_visible(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    ledger.open_account("account", Money("100"), (datetime.now(UTC) - timedelta(days=2)).date())
    imported = datetime.now(UTC) - timedelta(days=1)
    position = OpeningPosition(
        "stock", imported.date(), Quantity(2), Money("75"), imported,
        json.dumps({"source": "kite-opening-balance", "broker_account_id": "account"}),
    )
    ledger.import_opening_positions("account", "legacy", 0, [position])
    result = ledger.fund_broker_imports("account", "account")
    assert result == {"version": 2, "cash_deducted": "150"}
    assert ledger.projection("account").cash.amount == -50
    assert ledger.projection_at("account", imported.date()).cash.amount == 100
    assert ledger.fund_broker_imports("account", "account")["cash_deducted"] == "0"
    assert len(ledger.events("account")) == 2
    assert ledger.events("account")[0]["event_type"] == "OPENING_POSITION_IMPORTED"
    at = datetime.now(UTC) + timedelta(seconds=1)
    with pytest.raises(DomainValidationError, match="buy fill exceeds"):
        ledger.record_fills("account", "buy", 2, [Fill("other", at.date(), FillSide.BUY, Quantity(1), Money("1"), executed_at=at)])
    with pytest.raises(DomainValidationError, match="withdrawal exceeds"):
        ledger.record_cash_transfer("account", "withdraw", 2, "WITHDRAW", Money("1"), reason="test")
    with patch("src.domains.portfolio_accounting.portfolio_performance.calculate_xirr", return_value=None) as xirr:
        PortfolioPerformance(ledger).calculate_xirr("account", Decimal(100), at.date())
    assert [amount for _, amount in xirr.call_args.args[0]] == [Decimal(-100), Decimal(100)]
    ledger.record_fills("account", "sell", 2, [Fill("stock", at.date(), FillSide.SELL, Quantity(1), Money("100"), executed_at=at)])
    assert ledger.projection("account").cash.amount == 50
    assert ledger.projection("account").open_lots[0].remaining_units.units == 1
    assert ledger.fund_broker_imports("account", "account")["cash_deducted"] == "0"
