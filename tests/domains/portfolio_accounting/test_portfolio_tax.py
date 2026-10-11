from datetime import date
from decimal import Decimal

from src.domains.portfolio_accounting.portfolio_tax import portfolio_tax_estimates


def trade(bought, sold, gain):
    return {"buy_date": bought, "sell_date": sold, "buy_gross_price": "100",
            "sell_price": str(Decimal(100) + gain), "units": 1}


def test_tax_years_exemption_cess_and_same_year_loss_offsets():
    estimates = portfolio_tax_estimates([
        trade("2026-01-01", "2026-04-02", 100),
        trade("2026-01-01", "2026-05-01", -90),
        trade("2024-01-01", "2026-06-01", 200000),
        trade("2024-01-01", "2026-06-01", -100000),
        trade("2025-01-01", "2025-05-01", 10),
        trade("2026-01-01", "2026-11-01", 999999),  # Future sale excluded.
    ], date(2026, 10, 7))
    current, previous = estimates
    assert current["start_date"] == "2026-04-01"
    assert current["end_date"] == "2027-03-31"
    assert Decimal(current["short_term_gains"]) == 10
    assert Decimal(current["taxable_long_term_gains"]) == 0
    assert Decimal(current["estimated_tax"]) == Decimal("2.08")
    assert previous["start_date"] == "2025-04-01"
    assert Decimal(previous["estimated_tax"]) == Decimal("2.08")


def test_exact_twelve_months_and_leap_year_boundary():
    current, _ = portfolio_tax_estimates([
        trade("2025-07-01", "2026-07-01", 100),
        trade("2025-07-01", "2026-07-02", 100),
    ], date(2026, 10, 7))
    assert Decimal(current["short_term_gains"]) == 100
    assert Decimal(current["long_term_gains"]) == 100
    assert Decimal(current["estimated_tax"]) == Decimal("20.80")
    current, _ = portfolio_tax_estimates([
        trade("2024-02-29", "2025-02-28", 100),
        trade("2024-02-29", "2025-03-01", 100),
    ], date(2025, 3, 31))
    assert Decimal(current["short_term_gains"]) == 100
    assert Decimal(current["long_term_gains"]) == 100


def test_short_term_loss_offsets_long_term_gain_before_exemption():
    current, _ = portfolio_tax_estimates([
        trade("2026-01-01", "2026-05-01", -50000),
        trade("2024-01-01", "2026-06-01", 200000),
    ], date(2026, 10, 7))
    assert Decimal(current["taxable_short_term_gains"]) == 0
    assert Decimal(current["taxable_long_term_gains"]) == 25000
    assert Decimal(current["estimated_tax"]) == Decimal("3250.00")


def test_long_term_loss_does_not_offset_short_term_gain():
    current, _ = portfolio_tax_estimates([
        trade("2026-01-01", "2026-05-01", 100),
        trade("2024-01-01", "2026-06-01", -1000),
    ], date(2026, 10, 7))
    assert Decimal(current["estimated_tax"]) == Decimal("20.80")


def test_losses_do_not_cross_financial_years_and_negative_year_has_zero_tax():
    current, previous = portfolio_tax_estimates([
        trade("2025-01-01", "2026-03-31", -1000),
        trade("2026-01-01", "2026-04-01", 100),
        trade("2025-01-01", "2026-03-01", 10),
    ], date(2026, 10, 7))
    assert Decimal(current["estimated_tax"]) == Decimal("20.80")
    assert Decimal(previous["estimated_tax"]) == 0
