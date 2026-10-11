from datetime import date
from decimal import Decimal

from src.domains.market_data import MarketRepository, NormalizedBar
from src.domains.reference_data import ReferenceDataRepository, TrackedInstrument


def test_fetch_coverage_uses_completed_provider_windows_not_bar_boundaries(tmp_path):
    database = tmp_path / "system.db"
    reference = ReferenceDataRepository(database)
    market = MarketRepository(database)
    observed_on = date(2026, 1, 1)
    reference.upsert_instruments(
        [TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "1", observed_on)]
    )
    market.upsert_bars(
        "stock",
        (
            NormalizedBar(
                "stock", date(2025, 1, 2), Decimal(10), Decimal(11), Decimal(9), Decimal(10), 1
            ),
            NormalizedBar(
                "stock", date(2025, 12, 30), Decimal(10), Decimal(11), Decimal(9), Decimal(10), 1
            ),
        ),
        "snapshot",
        has_traded_volume=True,
    )
    assert not market.has_coverage("stock", date(2025, 1, 1), date(2025, 12, 31))

    market.record_fetch_coverage(
        "stock", date(2025, 1, 1), date(2025, 6, 30), provider="kite", bar_count=1
    )
    market.record_fetch_coverage(
        "stock", date(2025, 7, 1), date(2025, 12, 31), provider="kite", bar_count=1
    )

    assert market.has_coverage("stock", date(2025, 1, 1), date(2025, 12, 31))
