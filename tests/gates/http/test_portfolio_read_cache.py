from datetime import date, datetime

from flask import Flask

from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.gates.http import portfolio
from src.gates.repositories import MarketRepository, NormalizedBar, TrackedInstrument
from src.platform_kernel import Money, Quantity


def setup(tmp_path):
    database = tmp_path / "cache.db"
    ledger, market = Ledger(database), MarketRepository(database)
    day = date(2026, 2, 2)
    ledger.open_account("account", Money(1000), date(2026, 2, 1))
    market.upsert_instruments([TrackedInstrument("abc", "ABC", "ABC", "NSE", "1", day)])
    ledger.record_fills(
        "account",
        "buy",
        0,
        [
            Fill("abc", day, FillSide.BUY, Quantity(1), Money(100)),
        ],
    )
    market.upsert_bars("abc", [NormalizedBar("abc", day, 110, 110, 110, 110, 1)], "prices")
    app = Flask(__name__)
    app.register_blueprint(portfolio.create_portfolio_blueprint(ledger, market))
    return app.test_client(), ledger, market, day


def test_revisits_reuse_calculations_and_market_corrections_invalidate(tmp_path, monkeypatch):
    client, ledger, market, day = setup(tmp_path)
    value_loader, history_loader = portfolio.portfolio_valuation, portfolio.portfolio_history
    calls = {"value": 0, "history": 0}

    def value(*args, **kwargs):
        calls["value"] += 1
        return value_loader(*args, **kwargs)

    def history(*args, **kwargs):
        calls["history"] += 1
        return history_loader(*args, **kwargs)

    monkeypatch.setattr(portfolio, "portfolio_valuation", value)
    monkeypatch.setattr(portfolio, "portfolio_history", history)
    base = "/api/portfolio/accounts/account/valuation"
    for _ in range(2):
        assert client.get(f"{base}?as_of_date={day}").json["equity"] == "1010"
        assert (
            client.get(f"{base}/history?as_of_date={day}").json["history"][-1]["equity"] == "1010"
        )
    assert calls == {"value": 1, "history": 1}
    market.upsert_bars("abc", [NormalizedBar("abc", day, 120, 120, 120, 120, 1)], "corrected")
    assert client.get(f"{base}?as_of_date={day}").json["equity"] == "1020"
    assert client.get(f"{base}/history?as_of_date={day}").json["history"][-1]["equity"] == "1020"
    assert calls == {"value": 2, "history": 2}
    ledger.record_cash_transfer(
        "account",
        "deposit",
        1,
        "DEPOSIT",
        Money(10),
        reason="funding",
        occurred_at=datetime.fromisoformat("2026-02-02T12:00:00+05:30"),
    )
    assert client.get(f"{base}?as_of_date={day}").json["equity"] == "1030"
    assert client.get(f"{base}/history?as_of_date={day}").json["history"][-1]["equity"] == "1030"


def test_persisted_response_does_not_decorate_the_cached_read_model(tmp_path):
    client, _ledger, _market, day = setup(tmp_path)
    url = f"/api/portfolio/accounts/account/valuation?as_of_date={day}"
    assert "snapshot_id" not in client.get(url).json
    assert "snapshot_id" in client.get(url + "&persist=1").json
    assert "snapshot_id" not in client.get(url).json


def test_dates_and_accounts_have_separate_results(tmp_path):
    client, ledger, _market, day = setup(tmp_path)
    ledger.open_account("other", Money(50), date(2026, 2, 1))
    base = "/api/portfolio/accounts"
    assert client.get(f"{base}/account/valuation?as_of_date={day}").json["equity"] == "1010"
    assert client.get(f"{base}/account/valuation?as_of_date=2026-02-01").json["equity"] == "1000"
    assert client.get(f"{base}/other/valuation?as_of_date={day}").json["equity"] == "50"
    assert client.get(f"{base}/missing/valuation?as_of_date={day}").status_code == 400
