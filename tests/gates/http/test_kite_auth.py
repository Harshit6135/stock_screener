from flask import Blueprint, Flask

from src.gates.http.kite_auth import create_kite_auth_blueprint


def test_successful_profile_kite_callback_redirects_to_dashboard():
    class FakeKiteAuth:
        token_exists = False

        @staticmethod
        def login_url():
            return "https://kite.example/login"

        def exchange_request_token(self, request_token):
            assert request_token == "request-token"
            self.token_exists = True

    app = Flask(__name__)
    app.secret_key = "test"
    dashboard_blueprint = Blueprint("dashboard_v2", __name__)

    @dashboard_blueprint.get("/")
    def dashboard():
        return "dashboard"

    app.register_blueprint(dashboard_blueprint)
    app.register_blueprint(create_kite_auth_blueprint(FakeKiteAuth()))
    client = app.test_client()

    started = client.post("/api/v2/integrations/kite/market-data/authorize")
    assert started.status_code == 200
    callback = client.get(
        "/integrations/kite/market-data/callback?status=success&request_token=request-token"
    )

    assert callback.status_code == 302
    assert callback.headers["Location"].endswith("/")
    assert client.post("/api/v2/integrations/kite/authorize").status_code == 404
    assert client.get("/integrations/kite/callback").status_code == 404
