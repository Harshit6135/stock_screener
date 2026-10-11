"""Fresh market-data schema owned by the market-data domain."""

from pathlib import Path

from src.platform_kernel.sqlite import migrate_sqlite


def migrate_market_data(path: str | Path) -> None:
    """Create the current market-data schema."""
    migrate_sqlite(
        path,
        "market_data",
        {
            1: (
                """CREATE TABLE IF NOT EXISTS market_bars (
                    instrument_id TEXT NOT NULL, as_of_date TEXT NOT NULL,
                    open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL,
                    close TEXT NOT NULL, volume INTEGER NOT NULL, snapshot_id TEXT NOT NULL,
                    PRIMARY KEY(instrument_id, as_of_date),
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                "CREATE INDEX IF NOT EXISTS market_bars_date ON market_bars(as_of_date)",
                """CREATE TABLE IF NOT EXISTS market_index_quotes (
                    instrument_id TEXT PRIMARY KEY, exchange TEXT NOT NULL, symbol TEXT NOT NULL,
                    last_price TEXT NOT NULL, prev_close TEXT NOT NULL,
                    change_percent REAL NOT NULL, observed_at TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                """CREATE TABLE IF NOT EXISTS market_index_quote_history (
                    instrument_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                    last_price TEXT NOT NULL, prev_close TEXT NOT NULL,
                    change_percent REAL NOT NULL, snapshot_id TEXT NOT NULL,
                    PRIMARY KEY(instrument_id, observed_at),
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                "CREATE INDEX IF NOT EXISTS market_index_quote_history_recent ON market_index_quote_history(instrument_id, observed_at DESC)",
                """CREATE TABLE IF NOT EXISTS market_indicators (
                    indicator_set TEXT NOT NULL, instrument_id TEXT NOT NULL,
                    as_of_date TEXT NOT NULL, values_json TEXT NOT NULL,
                    source_snapshot_id TEXT NOT NULL, calculated_at TEXT NOT NULL,
                    PRIMARY KEY(indicator_set, instrument_id, as_of_date),
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                "CREATE INDEX IF NOT EXISTS market_indicators_date ON market_indicators(indicator_set, as_of_date)",
                """CREATE TABLE IF NOT EXISTS market_history_revisions (
                    instrument_id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                """CREATE TABLE IF NOT EXISTS data_quality_events (
                    event_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL,
                    as_of_date TEXT NOT NULL, check_type TEXT NOT NULL,
                    severity TEXT NOT NULL, detail_json TEXT NOT NULL, detected_at TEXT NOT NULL,
                    UNIQUE(instrument_id, as_of_date, check_type, detail_json),
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                "CREATE INDEX IF NOT EXISTS data_quality_events_instrument_date ON data_quality_events(instrument_id, as_of_date)",
                "CREATE INDEX IF NOT EXISTS data_quality_events_detected ON data_quality_events(detected_at DESC, event_id DESC)",
                """CREATE TABLE IF NOT EXISTS market_fetch_coverage (
                    instrument_id TEXT NOT NULL, start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL, provider TEXT NOT NULL,
                    coverage_context TEXT NOT NULL CHECK(coverage_context IN ('regular', 'exit_only')),
                    fetched_at TEXT NOT NULL, bar_count INTEGER NOT NULL,
                    PRIMARY KEY(instrument_id, start_date, end_date, provider, coverage_context),
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                "CREATE INDEX IF NOT EXISTS market_fetch_coverage_range ON market_fetch_coverage(instrument_id, provider, coverage_context, start_date, end_date)",
            ),
            2: (
                "CREATE INDEX IF NOT EXISTS market_bars_date_instrument ON market_bars(as_of_date, instrument_id)",
            ),
        },
    )
