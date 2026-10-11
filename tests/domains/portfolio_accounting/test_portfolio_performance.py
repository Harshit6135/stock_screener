from datetime import date
from decimal import Decimal

from src.domains.portfolio_accounting import PortfolioPerformance
from src.domains.portfolio_accounting.portfolio_performance import (
    calculate_open_holdings_xirr,
    calculate_xirr,
)


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


def test_same_day_flows_cannot_be_annualized_even_with_gain():
    day = date(2026, 10, 5)
    assert calculate_xirr([(day, Decimal(-400000)), (day, Decimal("450611.04"))]) is None
    assert calculate_xirr([(day, Decimal(-100)), (day, Decimal(100))]) is None


def test_solver_matches_excel_reference_and_handles_negative_return():
    flows = [
        (date(2008, 1, 1), Decimal(-10000)),
        (date(2008, 3, 1), Decimal(2750)),
        (date(2008, 10, 30), Decimal(4250)),
        (date(2009, 2, 15), Decimal(3250)),
        (date(2009, 4, 1), Decimal(2750)),
    ]
    assert abs(calculate_xirr(flows) - Decimal("0.373362535")) < Decimal("1e-8")
    assert abs(
        calculate_xirr([(date(2021, 1, 1), Decimal(-100)), (date(2022, 1, 1), Decimal(10))])
        + Decimal("0.9")
    ) < Decimal("1e-10")
    assert (
        calculate_xirr(
            list(reversed([(date(2021, 1, 1), Decimal(-100)), (date(2022, 1, 1), Decimal(100))]))
        )
        == 0
    )


def test_open_holdings_return_uses_remaining_lot_dates_and_same_day_buys():
    holdings = [
        {
            "acquisition_date": "2021-01-01",
            "cost": "100",
            "market_value": "120",
            "price": "120",
            "purchase_date_known": True,
        },
        {
            "acquisition_date": "2022-01-01",
            "cost": "50",
            "market_value": "50",
            "price": "50",
            "purchase_date_known": True,
        },
    ]
    assert abs(calculate_open_holdings_xirr(holdings, date(2022, 1, 1)) - Decimal("0.2")) < Decimal(
        "1e-10"
    )
    holdings[0]["purchase_date_known"] = False
    assert calculate_open_holdings_xirr(holdings, date(2022, 1, 1)) is None
    holdings[0]["purchase_date_known"] = True
    holdings[0]["price"] = None
    assert calculate_open_holdings_xirr(holdings, date(2022, 1, 1)) is None


def test_funded_import_history_does_not_annualize_old_gains_since_recent_cash():
    class ImportedLedger:
        def accounts(self):
            return [{"account_id": "account", "opening_cash": "1000"}]

        def events(self, _account_id):
            return [
                {
                    "version": 1,
                    "event_type": "OPENING_POSITION_IMPORTED",
                    "occurred_at": "2026-10-04T12:00:00+05:30",
                    "event": {
                        "instrument_id": "stock",
                        "units": 10,
                        "unit_cost": "10",
                        "acquisition_date": "2026-10-04",
                    },
                },
                {
                    "version": 2,
                    "event_type": "IMPORTED_POSITION_FUNDED",
                    "occurred_at": "2026-10-04T12:00:01+05:30",
                    "event": {"import_versions": [1]},
                },
                {
                    "version": 3,
                    "event_type": "OPEN_LOTS_RECONCILED",
                    "occurred_at": "2026-10-05T12:00:00+05:30",
                    "event": {
                        "instrument_id": "stock",
                        "lots": [{"date": "2026-05-04", "units": 10, "unit_cost": "10"}],
                    },
                },
            ]

    performance = PortfolioPerformance(ImportedLedger())
    assert performance.calculate_xirr("account", Decimal(1100), date(2026, 10, 5)) is None
    # Before reconciliation, the future event must not affect that valuation.
    assert performance.calculate_xirr("account", Decimal(1000), date(2026, 10, 4)) is None
