"""Account-scoped WebSocket quotes, separate from historical bars and fills."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

from kiteconnect import KiteTicker

from src.application.providers import KiteStreamingProvider
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError


class LiveQuotes:
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


class LiveQuoteStream:
    """Explicitly started read-only stream using the owning broker session."""

    def __init__(self, accounts, market, quotes, lease, alerts, ticker_factory=KiteTicker):
        self.accounts, self.market, self.quotes = accounts, market, quotes
        self.lease, self.alerts, self.ticker_factory = lease, alerts, ticker_factory
        self.provider = None
        self._lock = RLock()

    def start(self, account_id, instrument_ids):
        if not isinstance(account_id, str) or not account_id.strip():
            raise DomainValidationError("stream account_id is required")
        if (not isinstance(instrument_ids, list) or not 1 <= len(instrument_ids) <= 500
                or any(not isinstance(item, str) or not item.strip() for item in instrument_ids)
                or len(set(instrument_ids)) != len(instrument_ids)):
            raise DomainValidationError("stream requires 1..500 unique instrument identities")
        with self._lock:
            if self.provider is not None:
                raise DomainValidationError("stop the existing live stream before starting another")
            binding = self.accounts.binding(account_id)
            self.accounts.validate(binding["broker_account_id"])
            credentials = self.accounts.get_credentials(binding["broker_account_id"])
            tokens = {}
            for instrument_id in instrument_ids:
                instrument = self.market.instrument_by_id(instrument_id)
                if instrument is None or instrument["exchange"] != "NSE":
                    raise DomainValidationError("stream instrument must have an NSE identity")
                try:
                    token = int(instrument["provider_token"])
                except (TypeError, ValueError, KeyError) as exc:
                    raise DomainValidationError("stream instrument has no valid provider token") from exc
                if token <= 0 or token in tokens:
                    raise DomainValidationError("stream provider tokens must be positive and unique")
                tokens[token] = instrument_id
            ticker = self.ticker_factory(credentials["api_key"], credentials["access_token"])
            def ingest(payload):
                with self._lock:
                    if self.provider is provider and self.lease.state()["enabled"]:
                        return self._ingest(payload)
                return None

            provider = KiteStreamingProvider(ticker, account_id, tokens, ingest)
            self.provider = provider
            self.lease.start(account_id, len(tokens))
            original_connect, original_close = provider._on_connect, provider._on_close

            def connected(ws, response):
                original_connect(ws, response)
                if self.provider is provider:
                    self.lease.connected(len(tokens))

            def closed(ws, code, reason):
                original_close(ws, code, reason)
                if self.provider is provider and self.lease.state()["enabled"]:
                    self.lease.mark_error("WebSocket disconnected; waiting for reconnect")

            provider._on_connect, provider._on_close = connected, closed
            ticker.on_error = lambda ws, code, reason: closed(ws, code, reason)
            ticker.on_noreconnect = lambda ws: closed(ws, None, None)
            try:
                provider.start()
            except Exception as exc:
                self.provider = None
                provider.stop()
                self.lease.mark_error("WebSocket connection failed")
                raise DomainValidationError("live quote connection failed") from exc
            return self.lease.state()

    def _ingest(self, payload):
        self.quotes.ingest(payload)
        self.lease.heartbeat()
        # Alert observations retain their existing fill-free contract.
        observations = [{key: item[key] for key in ("instrument_id", "price", "observed_at", "source")}
                        for item in payload["observations"]]
        try:
            self.alerts.ingest({"account_id": payload["account_id"], "observations": observations})
        except DomainValidationError:
            # Missing risk projections must not discard the persisted live quote.
            return {"quotes_persisted": True, "alert_status": "RISK_PROJECTION_UNAVAILABLE"}
        return {"quotes_persisted": True, "alert_status": "PROCESSED"}

    def stop(self):
        with self._lock:
            provider, self.provider = self.provider, None
            self.lease.stop()
            if provider is not None:
                provider.stop()
            return self.lease.state()
