from datetime import date
from decimal import Decimal

from src.domains.portfolio_accounting import PortfolioPerformance


class _LedgerFixture:
    def events(self, _account_id):
        return [
            {
                "event_type": "CASH_TRANSFER",
                "occurred_at": "2021-01-01T00:00:00+00:00",
                "event": {"direction": "DEPOSIT", "amount": "100000"},
            },
            {
                "event_type": "OPENING_POSITION_IMPORTED",
                "occurred_at": "2021-01-01T10:00:00+00:00",
                "event": {
                    "units": "100",
                    "unit_cost": "2000",
                    "acquisition_date": "2021-01-01",
                },
            },
        ]

    def accounts(self):
        return [{"account_id": "acct1", "opening_cash": "0"}]


def test_calculate_xirr_uses_external_flows_and_imported_cost_basis():
    performance = PortfolioPerformance(_LedgerFixture())

    xirr = performance.calculate_xirr("acct1", Decimal(400000), date(2022, 1, 1))

    assert xirr is not None
    assert xirr > Decimal(0)
