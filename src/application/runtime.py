"""Runtime configuration for the new backend-only application shell."""

import os
from pathlib import Path


class RuntimeConfig:
    """Configuration deliberately independent from the retired legacy config package."""

    SECRET_KEY = os.environ.get("SCREENER_SECRET_KEY", "local-development-only")
    DATA_DIRECTORY = Path(os.environ.get("SCREENER_DATA_DIRECTORY", "instance"))
    OPERATOR_TOKEN = os.environ.get("SCREENER_OPERATOR_TOKEN")
    JSON_SORT_KEYS = False
    MAX_CONTENT_LENGTH = 64 * 1024
