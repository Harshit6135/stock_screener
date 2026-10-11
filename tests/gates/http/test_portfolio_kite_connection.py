import time

from flask import Blueprint, Flask

from src.domains.execution.accounts import KiteAccounts
from src.gates.http.kite_accounts import create_kite_accounts_blueprint
from src.gates.http.kite_auth import create_kite_auth_blueprint


def test_portfolio_login_exchanges_token_for_selected_account_only(tmp_path):
    class Client:
        def __init__(self, api_key):
            assert api_key == "portfolio-key"

        def login_url(self):
            return "https://kite.example/login"

        def generate_session(self, request_token, api_secret):
            assert api_secret == "portfolio-secret"
            return {"access_token": "other-token" if request_token == "other" else "valid-token"}

        def set_access_token(self, token):
            self.token = token

        def profile(self):
            return {"user_id": "OTHER" if self.token == "other-token" else "OWNER"}

    accounts = KiteAccounts(str(tmp_path / "accounts.db"), client_factory=Client)
    accounts.register_account("Harshit", "Harshit", "portfolio-key", "portfolio-secret")
    accounts.register_account("second", "second", "portfolio-key", "portfolio-secret")
    app = Flask(__name__)
    app.secret_key = "test-session-key"
    dashboard = Blueprint("dashboard", __name__)
    dashboard.add_url_rule("/", "home", lambda: "home")
    app.register_blueprint(dashboard)
    app.register_blueprint(create_kite_accounts_blueprint(accounts, None))
    app.register_blueprint(create_kite_auth_blueprint(None, portfolio_accounts=accounts))
    client = app.test_client()
    start = "/api/broker-accounts/Harshit/authorize"
    callback = "/integrations/kite/portfolio/callback?status=success&request_token=request"
    assert client.get(callback).status_code == 503
    assert client.post(start).json == {"authorization_url": "https://kite.example/login"}
    response = client.get(callback)
    assert response.status_code == 302
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert accounts.get_credentials("Harshit")["access_token"] == "valid-token"
    assert accounts.get_credentials("second")["access_token"] is None
    assert client.get(callback).status_code == 503
    for legacy_path in ["/integrations/kite/callback", "/integrations/kite/market-data/callback"]:
        client.post(start)
        assert client.get(f"{legacy_path}?status=success&request_token=request").status_code == 302
        assert accounts.get_credentials("Harshit")["access_token"] == "valid-token"
        assert accounts.get_credentials("second")["access_token"] is None
    assert "valid-token" not in client.get("/api/broker-accounts").text
    client.post(start)
    assert client.get(callback.replace("request_token=request", "request_token=other")).status_code == 400
    assert accounts.get_credentials("Harshit")["access_token"] == "valid-token"
    client.post(start)
    with client.session_transaction() as session:
        session["portfolio_broker_authorization"] = {
            "broker_account_id": "Harshit", "started_at": time.time() - 601
        }
    assert client.get(callback).status_code == 400
    client.post(start)
    assert client.get(callback.replace("status=success", "status=cancelled")).status_code == 400
    client.post(start)
    assert client.get(callback.replace("&request_token=request", "")).status_code == 400
    assert client.post("/api/broker-accounts/Harshit/access-token", json={"access_token": "manual"}).status_code == 404
