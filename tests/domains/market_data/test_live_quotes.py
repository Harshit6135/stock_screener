from datetime import UTC, datetime, timedelta

import pytest

from src.domains.market_data import LiveQuotes
from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection

NOW = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)


def observation(price="100", observed=NOW, received=NOW, verified=True, instrument="stock"):
    return {
        "instrument_id": instrument,
        "price": price,
        "observed_at": observed.isoformat(),
        "received_at": received.isoformat(),
        "source": "kite-stream",
        "exchange_timestamp_available": verified,
    }


def ingest(store, item, account="ledger"):
    return store.ingest({"account_id": account, "observations": [item]})


def test_quote_persistence_scope_and_out_of_order_ticks(tmp_path):
    database = tmp_path / "system.db"
    store = LiveQuotes(database, lambda: NOW)
    assert ingest(store, observation())["fills_created"] == 0
    ingest(store, observation("20", observed=NOW - timedelta(seconds=1)))
    ingest(store, observation("55"), "another-ledger")
    restarted = LiveQuotes(database, lambda: NOW)
    assert restarted.execution_quote("ledger", "stock")["price"] == "100"
    assert restarted.execution_quote("another-ledger", "stock")["price"] == "55"
    assert restarted.read("missing", "stock")["freshness"] == "MISSING"


def test_previous_close_follows_the_accepted_tick_and_does_not_leak_between_sessions(tmp_path):
    database = tmp_path / "system.db"
    store = LiveQuotes(database, lambda: NOW)
    ingest(store, {**observation(), "previous_close": "90"})
    ingest(store, {**observation(observed=NOW - timedelta(seconds=1)), "previous_close": "999"})
    assert LiveQuotes(database, lambda: NOW).read("ledger", "stock")["previous_close"] == "90"
    tomorrow = NOW + timedelta(days=1)
    ingest(store, observation(observed=tomorrow, received=tomorrow))
    assert store.read("ledger", "stock")["previous_close"] is None


def test_previous_close_migration_preserves_existing_quotes(tmp_path):
    database = tmp_path / "system.db"
    migrate_sqlite(database, "live_quotes", {1: (
        """CREATE TABLE live_quotes (
            account_id TEXT NOT NULL, instrument_id TEXT NOT NULL,
            price TEXT NOT NULL, observed_at TEXT NOT NULL, received_at TEXT NOT NULL,
            source TEXT NOT NULL, exchange_timestamp_available INTEGER NOT NULL,
            PRIMARY KEY(account_id, instrument_id))""",
    )})
    with sqlite_connection(database) as connection:
        connection.execute("INSERT INTO live_quotes VALUES (?, ?, ?, ?, ?, ?, ?)",
                           ("ledger", "stock", "100", NOW.isoformat(), NOW.isoformat(),
                            "kite-stream", 1))
    store = LiveQuotes(database, lambda: NOW)
    quote = store.execution_quote("ledger", "stock")
    assert quote["price"] == "100"
    assert quote["previous_close"] is None
    ingest(store, {**observation(received=NOW + timedelta(seconds=1)), "previous_close": "90"})
    assert store.read("ledger", "stock")["previous_close"] == "90"


@pytest.mark.parametrize("close", ["NaN", "Infinity", "0", "-1", True, "bad"])
def test_invalid_previous_close_rejects_the_batch(tmp_path, close):
    store = LiveQuotes(tmp_path / "system.db", lambda: NOW)
    with pytest.raises(DomainValidationError):
        ingest(store, {**observation(), "previous_close": close})
    assert store.read("ledger", "stock")["freshness"] == "MISSING"


@pytest.mark.parametrize(
    ("item", "status"),
    [
        (observation(observed=NOW - timedelta(seconds=61)), "STALE"),
        (observation(received=NOW - timedelta(seconds=61)), "STALE"),
        (observation(observed=NOW + timedelta(seconds=6)), "CLOCK_SKEW"),
        (observation(received=NOW + timedelta(seconds=6)), "CLOCK_SKEW"),
        (observation(verified=False), "UNVERIFIED_TIMESTAMP"),
    ],
)
def test_execution_rejects_unusable_quotes(tmp_path, item, status):
    store = LiveQuotes(tmp_path / "system.db", lambda: NOW)
    ingest(store, item)
    assert store.read("ledger", "stock")["freshness"] == status
    with pytest.raises(DomainValidationError, match=status):
        store.execution_quote("ledger", "stock")


@pytest.mark.parametrize("price", ["NaN", "Infinity", "0", "-1"])
def test_invalid_quote_batch_is_atomic(tmp_path, price):
    store = LiveQuotes(tmp_path / "system.db", lambda: NOW)
    with pytest.raises(DomainValidationError):
        store.ingest(
            {
                "account_id": "ledger",
                "observations": [observation(), observation(price, instrument="bad")],
            }
        )
    assert store.read("ledger", "stock")["freshness"] == "MISSING"
