import json

from kiteconnect.exceptions import TokenException
from requests.exceptions import ConnectionError as RequestConnectionError

from src.domains.execution.kite_auth import KiteAuthService, KiteCredentials


class Client:
    calls = 0

    def __init__(self, api_key):
        self.api_key = api_key

    def set_access_token(self, token):
        self.token = token

    def profile(self):
        Client.calls += 1
        if self.token == "expired-secret":
            raise TokenException("expired")
        if self.token == "offline-secret":
            raise RequestConnectionError("offline")
        return {"user_id": "user"}


def test_market_session_expiry_network_failure_and_refresh(tmp_path):
    token_path = tmp_path / "token.txt"
    service = KiteAuthService(KiteCredentials("api-key", "api-secret"), token_path, Client)
    assert service.session_status()["status"] == "MISSING"
    token_path.write_text("expired-secret")
    status = service.session_status()
    assert status["login_required"] is True
    assert "secret" not in json.dumps(status)
    token_path.write_text("active-secret")
    assert service.session_status()["status"] == "ACTIVE"
    assert service.stream_credentials() == {"api_key": "api-key", "access_token": "active-secret"}
    token_path.write_text("offline-secret")
    status = service.session_status()
    assert status["status"] == "UNAVAILABLE"
    assert status["login_required"] is False
