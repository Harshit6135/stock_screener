"""Fresh reference-data schema owned by the reference-data domain."""

from pathlib import Path

from src.platform_kernel.sqlite import migrate_sqlite


def migrate_reference_data(path: str | Path) -> None:
    """Create the current reference-data schema."""
    migrate_sqlite(
        path,
        "reference_data",
        {
            1: (
                """CREATE TABLE IF NOT EXISTS reference_instruments (
                    instrument_id TEXT PRIMARY KEY, isin TEXT NOT NULL,
                    symbol TEXT NOT NULL, exchange TEXT NOT NULL,
                    provider_token TEXT NOT NULL, observed_on TEXT NOT NULL,
                    series TEXT NOT NULL DEFAULT 'EQ',
                    UNIQUE(exchange, symbol, isin))""",
                "CREATE INDEX IF NOT EXISTS reference_instruments_symbol ON reference_instruments(exchange, symbol)",
                """CREATE TABLE IF NOT EXISTS reference_token_observations (
                    instrument_id TEXT NOT NULL, observed_on TEXT NOT NULL,
                    provider_token TEXT NOT NULL,
                    PRIMARY KEY(instrument_id, observed_on),
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                """CREATE TABLE IF NOT EXISTS universe_membership (
                    isin TEXT PRIMARY KEY, instrument_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, exchange TEXT NOT NULL,
                    membership_type TEXT NOT NULL, first_eligible_date TEXT NOT NULL,
                    initial_market_cap REAL NOT NULL, threshold_crore REAL NOT NULL,
                    source TEXT NOT NULL, snapshot_date TEXT NOT NULL,
                    last_market_cap REAL NOT NULL,
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                "CREATE INDEX IF NOT EXISTS universe_membership_instrument ON universe_membership(instrument_id)",
                """CREATE TABLE IF NOT EXISTS universe_build_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    snapshot_date TEXT NOT NULL, threshold_crore REAL NOT NULL,
                    source TEXT NOT NULL, total_tracked INTEGER NOT NULL,
                    resolved_count INTEGER NOT NULL, unresolved_count INTEGER NOT NULL,
                    member_count INTEGER NOT NULL, completed_at TEXT NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS universe_snapshots (
                    snapshot_id TEXT PRIMARY KEY, index_name TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL, source_url TEXT NOT NULL,
                    source_hash TEXT NOT NULL, member_count INTEGER NOT NULL,
                    raw_csv BLOB NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(index_name, snapshot_date))""",
                """CREATE TABLE IF NOT EXISTS universe_snapshot_members (
                    snapshot_id TEXT NOT NULL, isin TEXT NOT NULL, symbol TEXT NOT NULL,
                    company_name TEXT NOT NULL, industry TEXT NOT NULL, series TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id, isin),
                    FOREIGN KEY(snapshot_id) REFERENCES universe_snapshots(snapshot_id))""",
                "CREATE INDEX IF NOT EXISTS universe_snapshots_index_date ON universe_snapshots(index_name, snapshot_date DESC)",
                "CREATE INDEX IF NOT EXISTS universe_snapshot_members_symbol ON universe_snapshot_members(snapshot_id, symbol)",
                """CREATE TABLE IF NOT EXISTS universe_exit_eligibility (
                    instrument_id TEXT NOT NULL, isin TEXT NOT NULL,
                    symbol TEXT NOT NULL, decision_date TEXT NOT NULL,
                    decision_snapshot_id TEXT NOT NULL, target_session_date TEXT,
                    exit_only INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
                    session_source TEXT NOT NULL DEFAULT 'declared',
                    PRIMARY KEY(instrument_id, decision_snapshot_id),
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id),
                    FOREIGN KEY(decision_snapshot_id) REFERENCES universe_snapshots(snapshot_id))""",
                "CREATE INDEX IF NOT EXISTS universe_exit_eligibility_target ON universe_exit_eligibility(target_session_date)",
                """CREATE TABLE IF NOT EXISTS corporate_action_events (
                    event_id TEXT PRIMARY KEY, instrument_id TEXT,
                    isin TEXT NOT NULL, symbol TEXT NOT NULL, action_type TEXT NOT NULL,
                    ex_date TEXT NOT NULL, ratio_numerator REAL, ratio_denominator REAL,
                    raw_source_json TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'DETECTED',
                    baseline_revision TEXT, applied_factor REAL,
                    attempt_count INTEGER NOT NULL DEFAULT 0, last_attempt_at TEXT,
                    last_attempt_outcome TEXT, verified_at TEXT,
                    baseline_prices_json TEXT, verification_evidence_json TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                "CREATE INDEX IF NOT EXISTS corporate_action_events_state ON corporate_action_events(state, ex_date)",
                "CREATE INDEX IF NOT EXISTS corporate_action_events_instrument ON corporate_action_events(instrument_id, ex_date)",
                "CREATE UNIQUE INDEX IF NOT EXISTS corporate_action_events_unique ON corporate_action_events(isin, action_type, ex_date)",
                """CREATE TABLE IF NOT EXISTS corporate_action_watermark (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    last_checked_date TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            ),
        },
    )
