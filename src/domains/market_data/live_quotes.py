"""Durable account-scoped live quote state and freshness policy."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class LiveQuotes:
    """Persist and validate stream observations without creating execution fills."""

    def __init__(self, database: str | Path, clock=None):
        self.database = Path(database)
        self.clock = clock or (lambda: datetime.now(UTC))
        migrate_sqlite(self.database, "live_quotes", {1: (
            """CREATE TABLE IF NOT EXISTS live_quotes (
                account_id TEXT NOT NULL, instrument_id TEXT NOT NULL,
                price TEXT NOT NULL, observed_at TEXT NOT NULL,
                received_at TEXT NOT NULL, source TEXT NOT NULL,
                exchange_timestamp_available INTEGER NOT NULL,
                PRIMARY KEY(account_id, instrument_id))""",
        )})

    def ingest(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("account_id"), str) or not payload["account_id"].strip():
            raise DomainValidationError("live quotes require an explicit account")
        observations = payload.get("observations")
        if not isinstance(observations, list) or not observations:
            raise DomainValidationError("live quotes require observations")
        rows = []
        for item in observations:
            try:
                price = Decimal(str(item["price"]))
                observed = datetime.fromisoformat(item["observed_at"])
                received = datetime.fromisoformat(item["received_at"])
                instrument_id = item["instrument_id"]
                available = item["exchange_timestamp_available"]
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise DomainValidationError("invalid live quote") from exc
            if (not isinstance(instrument_id, str) or not instrument_id.strip()
                    or not price.is_finite() or price <= 0
                    or observed.utcoffset() is None or received.utcoffset() is None
                    or not isinstance(available, bool) or item.get("source") != "kite-stream"):
                raise DomainValidationError("invalid live quote")
            rows.append((payload["account_id"], instrument_id, str(price),
                         observed.astimezone(UTC).isoformat(), received.astimezone(UTC).isoformat(),
                         "kite-stream", int(available)))
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany("""INSERT INTO live_quotes VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, instrument_id) DO UPDATE SET
                price=excluded.price, observed_at=excluded.observed_at,
                received_at=excluded.received_at, source=excluded.source,
                exchange_timestamp_available=excluded.exchange_timestamp_available
                WHERE excluded.observed_at > live_quotes.observed_at
                   OR (excluded.observed_at = live_quotes.observed_at
                       AND excluded.received_at > live_quotes.received_at)""", rows)
        return {"quote_count": len(rows), "fills_created": 0}

    def read(self, account_id, instrument_id, *, max_age_seconds=60):
        if not isinstance(account_id, str) or not account_id.strip() or not isinstance(instrument_id, str) or not instrument_id.strip():
            raise DomainValidationError("quote account and instrument are required")
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or not 1 <= max_age_seconds <= 300:
            raise DomainValidationError("quote max_age_seconds must be 1..300")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute("SELECT * FROM live_quotes WHERE account_id=? AND instrument_id=?",
                                     (account_id, instrument_id)).fetchone()
        if row is None:
            return {"account_id": account_id, "instrument_id": instrument_id, "freshness": "MISSING"}
        quote = dict(row)
        now = self.clock().astimezone(UTC)
        observed = datetime.fromisoformat(quote["observed_at"])
        received = datetime.fromisoformat(quote["received_at"])
        age = (now - observed).total_seconds()
        received_age = (now - received).total_seconds()
        quote["age_seconds"] = round(age, 3)
        quote["exchange_timestamp_available"] = bool(quote["exchange_timestamp_available"])
        quote["freshness"] = (
            "CLOCK_SKEW" if age < -5 or received_age < -5 else
            "UNVERIFIED_TIMESTAMP" if not quote["exchange_timestamp_available"] else
            "STALE" if age > max_age_seconds or received_age > max_age_seconds else
            "PREVIOUS_SESSION" if observed.astimezone(ZoneInfo("Asia/Kolkata")).date() != now.astimezone(ZoneInfo("Asia/Kolkata")).date() else
            "FRESH"
        )
        return quote

    def execution_quote(self, account_id, instrument_id, *, max_age_seconds=60):
        quote = self.read(account_id, instrument_id, max_age_seconds=max_age_seconds)
        if quote["freshness"] != "FRESH":
            raise DomainValidationError(f"live execution quote unavailable: {quote['freshness']}")
        return quote
