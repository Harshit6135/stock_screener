from datetime import date
from decimal import Decimal

from flask import Flask

from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.gates.http.portfolio import create_portfolio_blueprint
from src.gates.repositories import MarketRepository, NormalizedBar, TrackedInstrument
from src.platform_kernel import Money, Quantity


def test_tax_excludes_unsold_units_and_is_unchanged_by_market_price(tmp_path):
    database = tmp_path / "tax.db"
    ledger, market = Ledger(database), MarketRepository(database)
    ledger.open_account("account", Money(10000), date(2026, 1, 1))
    market.upsert_instruments(
        [
            TrackedInstrument("abc", "ISINABC", "ABC", "NSE", "1", date(2026, 1, 1)),
            TrackedInstrument("def", "ISINDEF", "DEF", "NSE", "2", date(2026, 1, 1)),
        ]
    )
    ledger.record_fills(
        "account",
        "buys",
        0,
        [
            Fill("abc", date(2026, 1, 2), FillSide.BUY, Quantity(10), Money(100)),
            Fill("def", date(2026, 1, 2), FillSide.BUY, Quantity(5), Money(20)),
        ],
    )
    day = date(2026, 5, 1)
    for instrument, price in (("abc", 200), ("def", 100)):
        market.upsert_bars(
            instrument, [NormalizedBar(instrument, day, price, price, price, price, 100)], "test"
        )
    app = Flask(__name__)
    app.register_blueprint(create_portfolio_blueprint(ledger, market))
    client = app.test_client()
    url = "/api/portfolio/accounts/account/valuation?as_of_date=2026-05-01"
    before = client.get(url)
    assert before.status_code == 200
    assert Decimal(before.json["unrealised_gain"]) > 0
    assert all(Decimal(t["estimated_tax"]) == 0 for t in before.json["tax_estimates"])
    ledger.record_fills(
        "account",
        "partial-sale",
        2,
        [
            Fill("abc", day, FillSide.SELL, Quantity(4), Money(150)),
        ],
    )
    sold = client.get(url).json
    assert Decimal(sold["tax_estimates"][0]["short_term_gains"]) == 200
    assert Decimal(sold["tax_estimates"][0]["estimated_tax"]) == Decimal("41.60")
    assert Decimal(sold["tax_estimates"][1]["estimated_tax"]) == 0
    for instrument, price in (("abc", 9000), ("def", 5000)):
        market.upsert_bars(
            instrument, [NormalizedBar(instrument, day, price, price, price, price, 100)], "test"
        )
    repriced = client.get(url).json
    assert Decimal(repriced["unrealised_gain"]) > Decimal(sold["unrealised_gain"])
    assert repriced["tax_estimates"] == sold["tax_estimates"]
