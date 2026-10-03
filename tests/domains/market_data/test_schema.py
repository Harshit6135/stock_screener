"""Fresh market-data owner schema initialization."""

import sqlite3

from src.domains.market_data import MarketRepository


def test_market_repository_records_owner_migration_and_final_market_tables(tmp_path):
    database = tmp_path / "market.db"

    MarketRepository(database)

    with sqlite3.connect(database) as connection:
        versions = dict(
            connection.execute(
                "SELECT namespace, MAX(version) FROM system_schema_migrations GROUP BY namespace"
            )
        )
        coverage_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(market_fetch_coverage)")
        }
    assert versions == {"market_data": 1}
    assert "coverage_context" in coverage_columns
