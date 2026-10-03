"""Coordinate broker streaming with market quote and portfolio alert domains."""

from threading import RLock

from kiteconnect import KiteTicker

from src.platform_kernel import DomainValidationError


class LiveQuoteStream:
    """Explicitly started read-only stream using the owning broker session."""

    def __init__(self, accounts, market, quotes, lease, alerts, provider_factory, ticker_factory=KiteTicker):
        self.accounts, self.market, self.quotes = accounts, market, quotes
        self.lease, self.alerts = lease, alerts
        self.provider_factory, self.ticker_factory = provider_factory, ticker_factory
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

            provider = self.provider_factory(ticker, account_id, tokens, ingest)
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
        observations = [{key: item[key] for key in ("instrument_id", "price", "observed_at", "source")}
                        for item in payload["observations"]]
        try:
            self.alerts.ingest({"account_id": payload["account_id"], "observations": observations})
        except DomainValidationError:
            return {"quotes_persisted": True, "alert_status": "RISK_PROJECTION_UNAVAILABLE"}
        return {"quotes_persisted": True, "alert_status": "PROCESSED"}

    def stop(self):
        with self._lock:
            provider, self.provider = self.provider, None
            self.lease.stop()
            if provider is not None:
                provider.stop()
            return self.lease.state()
