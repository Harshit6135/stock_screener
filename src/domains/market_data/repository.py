"""SQLite read model for dated Kite instruments and normalized OHLCV bars."""

from __future__ import annotations

import math
from pathlib import Path

from src.platform_kernel import DomainValidationError

from .history_repository import MarketHistoryRepositoryMixin
from .index_quotes import IndexQuoteRepositoryMixin
from .schema import migrate_market_data


class MarketRepository(IndexQuoteRepositoryMixin, MarketHistoryRepositoryMixin):
    def __init__(self, path: str | Path, *, price_gap_threshold: float = 0.15):
        self.path = Path(path)
        if not math.isfinite(price_gap_threshold) or not 0 < price_gap_threshold < 1:
            raise DomainValidationError(
                "price gap threshold must be a finite fraction between zero and one"
            )
        self.price_gap_threshold = price_gap_threshold
        migrate_market_data(self.path)
