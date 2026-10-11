import sqlite3
from datetime import date

from src.domains.reference_data import ReferenceDataRepository, TrackedInstrument


def test_reference_repository_initializes_its_schema_without_market_repository(tmp_path):
    database = tmp_path / "reference.db"

    repository = ReferenceDataRepository(database)
    repository.upsert_instruments(
        [TrackedInstrument("instrument-1", "ISIN-1", "ONE", "NSE", "11", date(2026, 1, 2))]
    )

    assert repository.instrument_by_id("instrument-1")["series"] == "EQ"
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT MAX(version) FROM system_schema_migrations WHERE namespace='reference_data'"
            ).fetchone()[0]
            == 1
        )
