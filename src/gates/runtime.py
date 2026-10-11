"""Runtime configuration for the new backend-only application shell."""

import os
from pathlib import Path


class RuntimeConfig:
    """Runtime configuration for the local application."""

    SECRET_KEY = os.environ.get("SCREENER_SECRET_KEY", "local-development-only")
    DATA_DIRECTORY = Path(os.environ.get("SCREENER_DATA_DIRECTORY", "instance"))
    # Market-data access is a shared, read-only operational profile.
    MARKET_DATA_KITE_API_KEY = os.environ.get("MARKET_DATA_KITE_API_KEY")
    MARKET_DATA_KITE_API_SECRET = os.environ.get("MARKET_DATA_KITE_API_SECRET")
    MARKET_DATA_KITE_ACCESS_TOKEN_PATH = Path(
        os.environ.get(
            "SCREENER_MARKET_DATA_KITE_ACCESS_TOKEN_PATH",
            "access_token.txt",
        )
    )
    # Never fall back to the shared market-data profile for portfolio access.
    # These are process/deployment-local credentials until V4 has user identity
    # and an encrypted multi-user credential vault.
    PORTFOLIO_KITE_API_KEY = os.environ.get("PORTFOLIO_KITE_API_KEY")
    PORTFOLIO_KITE_API_SECRET = os.environ.get("PORTFOLIO_KITE_API_SECRET")
    PORTFOLIO_KITE_ACCESS_TOKEN_PATH = Path(
        os.environ.get("SCREENER_PORTFOLIO_KITE_ACCESS_TOKEN_PATH", "portfolio_access_token.txt")
    )
    PORTFOLIO_KITE_LIVE_EXECUTION = os.environ.get("SCREENER_PORTFOLIO_KITE_LIVE_EXECUTION", "false").lower() == "true"
    JSON_SORT_KEYS = False
    MAX_CONTENT_LENGTH = 64 * 1024
