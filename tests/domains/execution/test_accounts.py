from src.domains.execution import KiteCredentials, load_kite_credentials


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
