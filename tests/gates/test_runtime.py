from pathlib import Path

from run import create_app
from src.gates.runtime import RuntimeConfig


def test_minimal_app_page_and_kite_navigation(tmp_path):
    class TestConfig(RuntimeConfig):
        DATA_DIRECTORY = tmp_path
        KITE_API_KEY = None
        KITE_API_SECRET = None

    app = create_app(TestConfig)
    client = app.test_client()
    root = client.get("/")
    assert root.status_code == 200
    assert 'href="/integrations/kite"' in root.get_data(as_text=True)
    assert client.get("/app").status_code == 404
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/v2/actions/proposals?account_id=paper").status_code == 200
    assert client.get("/integrations/kite").status_code == 200


def test_real_app_has_no_legacy_dashboard_or_config_api(tmp_path):
    class TestConfig(RuntimeConfig):
        DATA_DIRECTORY = tmp_path
        KITE_API_KEY = None
        KITE_API_SECRET = None

    app = create_app(TestConfig)
    client = app.test_client()
    assert client.get("/dashboard").status_code == 404
    response = client.put(
        "/api/v1/config/momentum_config",
        json={"initial_capital": 125000, "max_positions": 10},
    )
    assert response.status_code == 404


def test_profile_pages_are_isolated_and_market_data_worker_has_no_portfolio_credentials(tmp_path):
    class TestConfig(RuntimeConfig):
        DATA_DIRECTORY = tmp_path
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
        ).status_code
        == 503
    )
    market_jobs = (
        app.extensions["screener_services"].worker.handlers["market.fetch-kite-bars"].__self__
    )
    assert not hasattr(market_jobs, "portfolio_credentials")
    assert not hasattr(market_jobs, "nse_csv_path")
    assert not hasattr(market_jobs, "bse_csv_path")
    handlers = app.extensions["screener_services"].worker.handlers
    assert "reference.sync-snapshot-instruments" in handlers
    assert "reference.sync-kite-instruments" not in handlers
    assert "reference.enrich-day0-universe" not in handlers
    assert Path(TestConfig.PORTFOLIO_KITE_ACCESS_TOKEN_PATH).exists() is False
