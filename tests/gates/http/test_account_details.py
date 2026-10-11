from datetime import date
from decimal import Decimal

from flask import Flask

from src.domains.execution import KiteAccounts
from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.gates.http.kite_accounts import create_kite_accounts_blueprint
from src.gates.http.portfolio import create_portfolio_blueprint
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.platform_kernel import Money, Quantity


def setup(tmp_path):
    database = tmp_path / "details.db"
    ledger, market = Ledger(database), MarketRepository(database)
    ledger.open_account("account", Money(300000), date(2026, 2, 1))
    accounts = KiteAccounts(str(database))
    accounts.register_account("account", "Account", "key", "secret")
    accounts.update_session("account", "token", "user")
    app = Flask(__name__)
    app.register_blueprint(create_portfolio_blueprint(ledger, market))
    app.register_blueprint(create_kite_accounts_blueprint(accounts, None))
    return app.test_client(), ledger, market, accounts


def details(**overrides):
    return {
        "display_name": "Updated account",
        "opening_date": "2026-01-01",
        "opening_cash": "400000.50",
        "expected_version": 0,
        "expected_details_version": 0,
        **overrides,
    }


def test_edit_preserves_identity_and_credentials_and_recalculates_cash(tmp_path):
    client, ledger, _, accounts = setup(tmp_path)
    response = client.put("/api/portfolio/accounts/account", json=details())
    assert response.status_code == 200, response.json
    assert response.json["account_id"] == "account"
    assert response.json["display_name"] == "Updated account"
    assert response.json["details_version"] == 1
    assert ledger.projection("account").cash.amount == Decimal("400000.50")
    assert accounts.get_credentials("account")["access_token"] == "token"
    assert client.put("/api/portfolio/accounts/account", json=details()).status_code == 409


def test_opening_date_cannot_cross_recorded_trade_and_no_history_is_deleted(tmp_path):
    client, ledger, market, _ = setup(tmp_path)
    market.upsert_instruments(
        [TrackedInstrument("abc", "ABC", "ABC", "NSE", "1", date(2026, 2, 1))]
    )
    ledger.record_fills(
        "account", "buy", 0, [Fill("abc", date(2026, 2, 9), FillSide.BUY, Quantity(1), Money(100))]
    )
    before = ledger.events("account")
    response = client.put(
        "/api/portfolio/accounts/account",
        json=details(opening_date="2026-02-10", expected_version=1),
    )
    assert response.status_code == 409 and "earliest" in response.json["error"]
    assert ledger.events("account") == before
    assert (
        client.put("/api/portfolio/accounts/account", json=details(expected_version=1)).status_code
        == 200
    )
    assert ledger.events("account") == before
    assert ledger.projection("account").cash.amount == Decimal("399900.50")


def test_credential_replacement_expires_session_and_summaries_never_return_secrets(tmp_path):
    client, _, _, accounts = setup(tmp_path)
    response = client.put("/api/broker-accounts/account", json={"account_name": "Renamed"})
    assert response.status_code == 200
    assert accounts.get_credentials("account")["access_token"] == "token"
    response = client.put(
        "/api/broker-accounts/account",
        json={"account_name": "Renamed", "api_key": "new-key", "api_secret": "new-secret"},
    )
    assert response.status_code == 200
    assert accounts.get_credentials("account")["access_token"] is None
    summaries = client.get("/api/broker-accounts").json
    assert "new-key" not in str(summaries) and "new-secret" not in str(summaries)
    assert (
        client.put(
            "/api/broker-accounts/account", json={"account_name": "Renamed", "api_key": "partial"}
        ).status_code
        == 400
    )
