from datetime import date, datetime
from decimal import Decimal

from flask import Flask

from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.gates.http.portfolio import create_portfolio_blueprint
from src.gates.repositories import MarketRepository, NormalizedBar, TrackedInstrument
from src.platform_kernel import Money, Quantity


def setup(tmp_path, missing_first_price=False):
    database = tmp_path / "history.db"
    ledger, market = Ledger(database), MarketRepository(database)
    ledger.open_account("account", Money(1000), date(2026, 2, 1))
    market.upsert_instruments(
        [TrackedInstrument("abc", "ABC", "ABC", "NSE", "1", date(2026, 2, 1))]
    )
    ledger.record_fills(
        "account",
        "buy",
        0,
        [
            Fill(
                "abc",
                date(2026, 2, 2),
                FillSide.BUY,
                Quantity(1),
                Money(100),
                executed_at=datetime.fromisoformat("2026-02-02T10:00:00+05:30"),
            )
        ],
    )
    ledger.record_cash_transfer(
        "account",
        "deposit",
        1,
        "DEPOSIT",
        Money(1000),
        reason="funding",
        occurred_at=datetime.fromisoformat("2026-02-04T00:00:00+05:30"),
    )
    bars = [
        NormalizedBar("abc", date(2026, 2, day), price, price, price, price, 1)
        for day, price in [(2, 110), (3, 90), (4, 90)]
        if day != 2 or not missing_first_price
    ]
    market.upsert_bars("abc", bars, "prices")
    app = Flask(__name__)
    app.register_blueprint(create_portfolio_blueprint(ledger, market))
    return app.test_client(), ledger


def test_curves_reconstruct_without_saved_snapshots_and_adjust_for_capital(tmp_path):
    client, ledger = setup(tmp_path)
    before = ledger.events("account")
    result = client.get(
        "/api/portfolio/accounts/account/valuation/history?as_of_date=2026-02-04"
    ).json
    rows = result["history"]
    assert [Decimal(row["equity"]) for row in rows] == [1000, 1010, 990, 1990]
    expected = Decimal(990) / 1010 - 1
    assert abs(Decimal(rows[2]["drawdown"]) - expected) < Decimal("1e-20")
    assert Decimal(rows[3]["drawdown"]) == Decimal(rows[2]["drawdown"])
    assert result["missing_price_days"] == 0
    assert not ledger.valuations("account")
    assert ledger.events("account") == before
    assert (
        client.get("/api/portfolio/accounts/account/valuation/history?as_of_date=2026-01-31").json[
            "history"
        ]
        == []
    )


def test_missing_historical_prices_are_reported_without_invented_values(tmp_path):
    client, _ledger = setup(tmp_path, True)
    result = client.get(
        "/api/portfolio/accounts/account/valuation/history?as_of_date=2026-02-04"
    ).json
    assert result["missing_price_days"] == 1
    assert result["missing_symbols"] == ["ABC"]
    assert "2026-02-02" not in [row["as_of_date"] for row in result["history"]]
