from pathlib import Path

from run import create_app
from src.application.kite_auth import KiteCredentials, load_kite_credentials
from src.application.runtime import RuntimeConfig


def test_portfolio_profile_never_uses_legacy_or_market_data_credentials():
    config = {
        "MARKET_DATA_KITE_API_KEY": "shared-key",
        "MARKET_DATA_KITE_API_SECRET": "shared-secret",
        "KITE_API_KEY": "legacy-key",
        "KITE_API_SECRET": "legacy-secret",
    }
    assert load_kite_credentials(config, profile="market_data") == KiteCredentials(
        api_key="shared-key", api_secret="shared-secret"
    )
    assert load_kite_credentials(config, profile="portfolio") is None


def test_profile_pages_are_isolated_and_market_data_worker_has_no_portfolio_credentials(tmp_path):
    class TestConfig(RuntimeConfig):
        DATA_DIRECTORY = tmp_path
        OPERATOR_TOKEN = "test-secret"
        MARKET_DATA_KITE_API_KEY = None
        MARKET_DATA_KITE_API_SECRET = None
        KITE_API_KEY = None
        KITE_API_SECRET = None
        PORTFOLIO_KITE_API_KEY = None
        PORTFOLIO_KITE_API_SECRET = None
        MARKET_DATA_KITE_ACCESS_TOKEN_PATH = tmp_path / "market-token.txt"
        PORTFOLIO_KITE_ACCESS_TOKEN_PATH = tmp_path / "portfolio-token.txt"

    app = create_app(TestConfig)
    client = app.test_client()
    assert client.get("/integrations/kite").status_code == 200
    portfolio = client.get("/integrations/kite/portfolio")
    assert portfolio.status_code == 200
    assert b"never falls back" in portfolio.data
    assert (
        client.post(
            "/api/v2/integrations/kite/portfolio/authorize",
            headers={"X-Operator-Token": "test-secret"},
        ).status_code
        == 503
    )
    market_jobs = (
        app.extensions["screener_services"].worker.handlers["market.fetch-kite-bars"].__self__
    )
    assert not hasattr(market_jobs, "portfolio_credentials")
    assert Path(TestConfig.PORTFOLIO_KITE_ACCESS_TOKEN_PATH).exists() is False
