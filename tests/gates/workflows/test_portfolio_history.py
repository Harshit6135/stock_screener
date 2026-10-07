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
    assert result["partial"] is True
    assert result["excluded_symbols"] == ["ABC"]
    assert [Decimal(row["equity"]) for row in result["history"]] == [1000, 1000, 1000, 2000]
    assert all(Decimal(row["drawdown"]) == 0 for row in result["history"])


def test_partial_curve_keeps_priced_stock_and_excludes_unpriced_cash_flows(tmp_path):
    client, ledger = setup(tmp_path)
    market = MarketRepository(tmp_path / "history.db")
    market.upsert_instruments([TrackedInstrument("missing", "MISSING", "MISSING", "NSE", "", date(2026, 2, 1))])
    ledger.record_fills("account", "missing-buy", 2, [Fill("missing", date(2026, 2, 2), FillSide.BUY, Quantity(1), Money(50), executed_at=datetime.fromisoformat("2026-02-02T11:00:00+05:30"))])
    ledger.record_fills("account", "missing-sell", 3, [Fill("missing", date(2026, 2, 3), FillSide.SELL, Quantity(1), Money(80))])
    original = ledger.events("account")
    result = client.get("/api/portfolio/accounts/account/valuation/history?as_of_date=2026-02-04").json
    assert result["excluded_symbols"] == ["MISSING"]
    assert [Decimal(r["equity"]) for r in result["history"]] == [1000, 1010, 990, 1990]
    assert ledger.events("account") == original


def test_closed_trades_change_cash_and_drawdown_after_sale(tmp_path):
    client, ledger = setup(tmp_path)
    ledger.record_fills("account", "sell", 2, [Fill("abc", date(2026, 2, 3), FillSide.SELL, Quantity(1), Money(80), Money(2))])
    result = client.get("/api/portfolio/accounts/account/valuation/history?as_of_date=2026-02-04").json
    assert [Decimal(r["equity"]) for r in result["history"]] == [1000, 1010, 978, 1978]
    assert result["partial"] is False
    assert Decimal(result["history"][2]["drawdown"]) < 0


def test_excluding_imported_stock_adjusts_only_its_curve_funding(tmp_path):
    from datetime import UTC
    from src.domains.portfolio_accounting import OpeningPosition
    _client, ledger = setup(tmp_path)
    ledger.import_opening_positions('account', 'positions', 2, [
        OpeningPosition('priced', date(2026, 2, 5), Quantity(1), Money(100), datetime.now(UTC), '{"source":"kite-opening-balance","broker_account_id":"account"}'),
        OpeningPosition('missing', date(2026, 2, 5), Quantity(1), Money(50), datetime.now(UTC), '{"source":"kite-opening-balance","broker_account_id":"account"}'),
    ])
    ledger.fund_broker_imports('account', 'account')
    before = ledger.projection('account')
    filtered = ledger.projection_at('account', None, excluded_instrument_ids={'missing'})
    assert filtered.cash.amount == before.cash.amount + 50
    assert {lot.instrument_id for lot in filtered.open_lots} == {'abc', 'priced'}
    assert ledger.projection('account') == before
