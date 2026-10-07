"""Kite instrument synchronization and bounded daily history ingestion."""

from __future__ import annotations

import logging

logger = logging.getLogger("screener." + __name__)
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from kiteconnect import KiteConnect  # type: ignore[import-untyped]
from kiteconnect.exceptions import KiteException
from requests.exceptions import RequestException

from src.domains.artifacts import ArtifactPublisher
from src.domains.market_data import NSE_INDEX_SYMBOLS, KiteHistoricalBarsProvider, NormalizedBar
from src.domains.portfolio_accounting import IntradayStopAlerts
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.market_ingestion import ingest_market_bars
from src.platform_kernel import DomainValidationError, QualityStatus
from src.platform_kernel.security import sanitize_error

PHASE2_BENCHMARK_SYMBOLS = NSE_INDEX_SYMBOLS


class KiteMarketJobs:
    def __init__(
        self,
        repository: MarketRepository,
        publisher: ArtifactPublisher,
        credentials: Any | None,
        token_path: str | Path,
        intraday_alerts: IntradayStopAlerts | None = None,
        ledger=None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.credentials = credentials
        self.token_path = Path(token_path)
        self.intraday_alerts = intraday_alerts
        self.ledger = ledger
        self._kite_dump_cache: dict[str, list[dict[str, Any]]] | None = None

    def _client(self) -> KiteConnect:
        if self.credentials is None:
            raise DomainValidationError("Kite credentials are not configured")
        try:
            token = self.token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise DomainValidationError("Kite access token is unavailable") from exc
        if not token:
            raise DomainValidationError("Kite access token is unavailable")
        client = KiteConnect(api_key=self.credentials.api_key)
        client.set_access_token(token)
        return client

    def _cached_kite_nse_dump(self) -> list[dict[str, Any]]:
        """Cache Kite NSE instrument dump per collection day."""
        today = datetime.now(UTC).date().isoformat()
        if self._kite_dump_cache is not None and today in self._kite_dump_cache:
            return self._kite_dump_cache[today]
        records = self._client().instruments("NSE")
        self._kite_dump_cache = {today: records}
        return records

    def corporate_history(
        self, instrument_id: str, start: date, end: date
    ) -> list[dict[str, object]]:
        identity = self.repository.instrument_by_id(instrument_id)
        if identity is None or identity["exchange"] != "NSE":
            raise DomainValidationError("corporate action instrument is not tracked on NSE")
        provider = KiteHistoricalBarsProvider(self._client())
        rows = []
        while start <= end:
            chunk_end = min(end, start + timedelta(days=1999))
            bars, _raw_records, quality_events = provider.get_bars_with_quality(
                str(identity["provider_token"]),
                start,
                chunk_end,
                symbol=str(identity["symbol"]),
                isin=str(identity["isin"]),
            )
            for quality_event in quality_events:
                event_date = date.fromisoformat(str(quality_event["as_of_date"]))
                self.repository.resolve_quality_events(
                    instrument_id,
                    event_date,
                    "provider_ohlc_source_unresolved",
                    {"method": quality_event["check_type"], **quality_event},
                )
                self.repository.record_quality_event(
                    instrument_id,
                    event_date,
                    str(quality_event["check_type"]),
                    str(quality_event["severity"]),
                    dict(quality_event),
                )
            rows.extend(
                {
                    "as_of_date": bar.as_of_date.isoformat(),
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": bar.volume,
                }
                for bar in bars
            )
            start = chunk_end + timedelta(days=1)
        return rows

    def sync_snapshot_instruments(
        self,
        payload: dict[str, Any],
        context: Any = None,
    ) -> dict[str, object]:
        """Resolve snapshot members against Kite's NSE instrument dump."""
        snapshot_id = payload.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise DomainValidationError("snapshot instrument sync requires snapshot_id")
        members = self.repository.universe_snapshot_members(snapshot_id, limit=1000)
        if not members:
            raise DomainValidationError("snapshot has no members to resolve")
        provider_records = self._cached_kite_nse_dump()
        observed_on = datetime.now(UTC).date()
        # Kite appends the NSE series to some trading symbols, e.g. HFCL-BE.
        provider_by_symbol: dict[str, dict[str, Any]] = {}
        for record in provider_records:
            ts = str(record.get("tradingsymbol", "")).upper()
            if ts and (ts not in provider_by_symbol or record.get("instrument_type") == "EQ"):
                provider_by_symbol[ts] = record
        records: list[TrackedInstrument] = []
        unresolved: list[dict[str, str]] = []
        seen: set[str] = set()
        for member in members:
            symbol = str(member["symbol"]).upper()
            isin = str(member["isin"])
            series = str(member.get("series", "EQ"))
            provider_record = provider_by_symbol.get(symbol)
            if provider_record is None and series.upper() == "BE":
                provider_record = provider_by_symbol.get(f"{symbol}-BE")
            if provider_record is None:
                unresolved.append(
                    {"isin": isin, "symbol": symbol, "reason": "absent_from_kite_nse_dump"}
                )
                continue
            instrument_id = str(uuid5(NAMESPACE_URL, f"NSE:{isin}"))
            if instrument_id in seen:
                continue
            seen.add(instrument_id)
            records.append(
                TrackedInstrument(
                    instrument_id,
                    isin,
                    symbol,
                    str(provider_record.get("exchange", "NSE")),
                    str(provider_record["instrument_token"]),
                    observed_on,
                    series=series,
                )
            )
        # Also resolve benchmarks
        for bm_symbol in sorted(PHASE2_BENCHMARK_SYMBOLS):
            bm_record = provider_by_symbol.get(bm_symbol)
            if bm_record is None:
                unresolved.append(
                    {
                        "isin": f"INDEX:{bm_symbol}",
                        "symbol": bm_symbol,
                        "reason": "benchmark_absent_from_kite_dump",
                    }
                )
                continue
            bm_isin = f"INDEX:{bm_symbol}"
            bm_id = str(uuid5(NAMESPACE_URL, f"NSE:INDEX:{bm_symbol}"))
            if bm_id not in seen:
                seen.add(bm_id)
                records.append(
                    TrackedInstrument(
                        bm_id,
                        bm_isin,
                        bm_symbol,
                        "NSE",
                        str(bm_record["instrument_token"]),
                        observed_on,
                    )
                )
        if not records:
            raise DomainValidationError("Kite dump resolved no snapshot members")
        self.repository.upsert_instruments(records)
        if context is not None:
            context.checkpoint(
                progress={
                    "stage": "snapshot_resolve",
                    "resolved": len(records),
                    "unresolved": len(unresolved),
                }
            )
        return {
            "snapshot_id": snapshot_id,
            "resolved_count": len(records),
            "unresolved": unresolved,
            "observed_on": observed_on.isoformat(),
        }

    def fetch_index_quotes(self, payload: dict[str, Any]) -> dict[str, object]:
        """Fetch a single timestamped Kite quote snapshot for all tracked indices."""
        if payload:
            raise DomainValidationError("index quote refresh takes no payload")
        tracked = []
        for symbol in sorted(PHASE2_BENCHMARK_SYMBOLS):
            try:
                instrument = self.repository.instrument(symbol, "NSE")
            except DomainValidationError:
                instrument = None
            tracked.append(("NSE", symbol, instrument))
        raw = self._client().ohlc([f"{exchange}:{symbol}" for exchange, symbol, _ in tracked])
        if not isinstance(raw, dict):
            raise DomainValidationError("Kite index quote response is invalid")
        observed_at = datetime.now(UTC).isoformat()
        quotes: list[dict[str, object]] = []
        for exchange, symbol, instrument in tracked:
            item = raw.get(f"{exchange}:{symbol}")
            if not isinstance(item, dict):
                continue
            if instrument is None:
                token = item.get("instrument_token")
                if not isinstance(token, int) or isinstance(token, bool) or token <= 0:
                    continue
                identity = TrackedInstrument(
                    str(uuid5(NAMESPACE_URL, f"NSE:INDEX:{symbol}")),
                    f"INDEX:{symbol}", symbol, "NSE", str(token),
                    datetime.now(UTC).date(),
                )
                self.repository.upsert_instruments([identity])
                instrument = self.repository.instrument(symbol, "NSE")
            try:
                last_price = Decimal(str(item["last_price"]))
                prev_close = Decimal(str(item["ohlc"]["close"]))
            except (KeyError, TypeError, InvalidOperation) as exc:
                raise DomainValidationError("Kite index quote has invalid prices") from exc
            if (
                not last_price.is_finite()
                or not prev_close.is_finite()
                or min(last_price, prev_close) <= 0
            ):
                raise DomainValidationError("Kite index quote has non-positive prices")
            quotes.append(
                {
                    "instrument_id": instrument["instrument_id"],
                    "exchange": exchange,
                    "symbol": symbol,
                    "last_price": str(last_price),
                    "prev_close": str(prev_close),
                    "change_percent": float((last_price / prev_close - 1) * 100),
                    "observed_at": observed_at,
                }
            )
        if not quotes:
            raise DomainValidationError("Kite returned no tracked index quotes")
        snapshot_id = str(uuid4())
        manifest = self.publisher.publish_json(
            "market/index_quotes/kite",
            snapshot_id,
            {"snapshot_id": snapshot_id, "observed_at": observed_at, "quotes": quotes},
        )
        self.repository.upsert_index_quotes(quotes, manifest.artifact_id)
        return {
            "artifact_id": manifest.artifact_id,
            "observed_at": observed_at,
            "quote_count": len(quotes),
        }

    def fetch_intraday_stop_alerts(self, payload: dict[str, Any]) -> dict[str, object]:
        """Poll current holding quotes and hand them to the durable alert model."""
        if self.intraday_alerts is None:
            raise DomainValidationError("intraday alert service is unavailable")
        if self.ledger is None:
            raise DomainValidationError("intraday alert ledger is unavailable")
        if (
            not isinstance(payload, dict)
            or set(payload) not in ({"account_id"}, {"account_id", "instrument_ids"})
            or not isinstance(payload.get("account_id"), str)
        ):
            raise DomainValidationError("intraday alert poll requires account_id")
        projection = self.ledger.projection(str(payload["account_id"]))
        requested = payload.get("instrument_ids")
        if requested is not None and (
            not isinstance(requested, list) or any(not isinstance(item, str) for item in requested)
        ):
            raise DomainValidationError("instrument_ids must be a list of strings")
        requested_ids = set(requested or [])
        holdings = [
            lot.instrument_id
            for lot in projection.open_lots
            if not requested_ids or lot.instrument_id in requested_ids
        ]
        if not holdings:
            raise DomainValidationError("account has no requested open holdings")
        # Holdings are portfolio state, not a paginated strategy result. Use
        # the complete retained reference catalog for quote polling.
        instruments = {
            instrument["instrument_id"]: instrument
            for instrument in self.repository.tracked_instruments()
        }
        keys = []
        for instrument_id in holdings:
            identity = instruments.get(instrument_id)
            if identity is not None:
                keys.append((instrument_id, f"{identity['exchange']}:{identity['symbol']}"))
        raw = self._client().ohlc([key for _, key in keys])
        observed_at = datetime.now(UTC).isoformat()
        observations = []
        for instrument_id, key in keys:
            item = raw.get(key) if isinstance(raw, dict) else None
            if not isinstance(item, dict) or "last_price" not in item:
                continue
            observations.append(
                {
                    "instrument_id": instrument_id,
                    "price": item["last_price"],
                    "observed_at": observed_at,
                    "source": "kite-ohlc",
                }
            )
        if not observations:
            raise DomainValidationError("Kite returned no holding quotes")
        return self.intraday_alerts.ingest(
            {"account_id": str(payload["account_id"]), "observations": observations}
        )

    def _current_history_isins(self) -> set[str]:
        snapshot = self.repository.latest_universe_snapshot("NIFTY 500")
        if snapshot is None:
            raise DomainValidationError("NIFTY 500 snapshot is unavailable for history fetch")
        members = self.repository.universe_snapshot_members(
            str(snapshot["snapshot_id"]), limit=1000
        )
        return {str(member["isin"]) for member in members}

    def _history_context(
        self,
        instrument: dict[str, Any],
        start: date,
        end: date,
        *,
        exit_only: bool = False,
        current_isins: set[str] | None = None,
    ) -> str:
        """Authorize provider history against the latest pinned NSE membership."""
        if instrument["exchange"] != "NSE":
            raise DomainValidationError("history fetch supports NSE instruments only")
        instrument_id = str(instrument["instrument_id"])
        symbol = str(instrument["symbol"])
        isin = str(instrument["isin"])
        if current_isins is None:
            current_isins = self._current_history_isins()
        if exit_only:
            if start != end or isin in current_isins or isin == f"INDEX:{symbol}":
                raise DomainValidationError("exit-only history requires one excluded stock session")
            eligible = self.repository.exit_eligible_instruments(target_date=start)
            if not any(str(row["instrument_id"]) == instrument_id for row in eligible):
                raise DomainValidationError(
                    "history session is not eligible for an exit-only fetch"
                )
            return "exit_only"
        if isin in current_isins or (
            symbol in PHASE2_BENCHMARK_SYMBOLS and isin == f"INDEX:{symbol}"
        ):
            return "regular"
        raise DomainValidationError("history fetch instrument is outside the current NSE snapshot")

    def fetch_bars(self, payload: dict[str, Any]) -> dict[str, object]:
        symbol = payload.get("symbol")
        exchange = payload.get("exchange", "NSE")
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(exchange, str)
            or exchange != "NSE"
            or ("exit_only" in payload and payload["exit_only"] is not True)
            or set(payload)
            not in (
                {"symbol", "start_date", "end_date"},
                {"symbol", "exchange", "start_date", "end_date"},
                {"symbol", "exchange", "start_date", "end_date", "exit_only"},
            )
        ):
            raise DomainValidationError(
                "bar fetch requires exchange, symbol, start_date and end_date"
            )
        try:
            start_date = date.fromisoformat(payload["start_date"])
            end_date = date.fromisoformat(payload["end_date"])
        except (TypeError, ValueError, KeyError) as exc:
            raise DomainValidationError("bar fetch dates must be ISO dates") from exc
        if start_date > end_date or end_date - start_date > timedelta(days=1999):
            raise DomainValidationError("bar fetch range must be at most 2000 calendar days")
        instrument = self.repository.instrument(symbol, exchange)
        instrument_id = str(instrument["instrument_id"])
        coverage_context = self._history_context(
            instrument, start_date, end_date, exit_only=payload.get("exit_only", False)
        )
        if self.repository.has_coverage(
            instrument_id, start_date, end_date, "kite", coverage_context=coverage_context
        ):
            return {
                "symbol": symbol,
                "exchange": exchange,
                "bar_count": 0,
                "skipped": True,
                "reason": "stored coverage already spans requested range",
                "first_date": start_date.isoformat(),
                "last_date": end_date.isoformat(),
            }
        fetched = KiteHistoricalBarsProvider(self._client()).get_bars(
            str(instrument["provider_token"]), start_date, end_date
        )
        if not fetched:
            self.repository.record_fetch_coverage(
                instrument_id,
                start_date,
                end_date,
                provider="kite",
                bar_count=0,
                coverage_context=coverage_context,
            )
            return {
                "symbol": symbol,
                "exchange": exchange,
                "bar_count": 0,
                "skipped": False,
                "reason": "provider returned no bars for the completed range",
                "first_date": None,
                "last_date": None,
            }
        bars = tuple(
            NormalizedBar(
                instrument_id,
                bar.as_of_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.traded_value,
            )
            for bar in fetched
        )
        raw, normalized = ingest_market_bars(
            self.publisher,
            "kite",
            bars,
            source_request={
                "symbol": symbol,
                "exchange": exchange,
                "provider_token": str(instrument["provider_token"]),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "coverage_context": coverage_context,
            },
            provider_version="kiteconnect-v5",
        )
        self.repository.upsert_bars(instrument_id, bars, normalized.artifact_id)
        self.repository.record_fetch_coverage(
            instrument_id,
            start_date,
            end_date,
            provider="kite",
            bar_count=len(bars),
            coverage_context=coverage_context,
        )
        return {
            "raw_artifact_id": raw.artifact_id,
            "artifact_id": normalized.artifact_id,
            "symbol": symbol,
            "exchange": exchange,
            "bar_count": len(bars),
            "first_date": bars[0].as_of_date.isoformat(),
            "last_date": bars[-1].as_of_date.isoformat(),
        }

    def fetch_bulk_bars(self, payload: dict[str, Any], context: Any) -> dict[str, object]:
        """Bound concurrent provider reads; keep writes and cancellation sequential."""
        import concurrent.futures

        if not isinstance(payload, dict) or set(payload) != {"items", "start_date", "end_date"}:
            raise DomainValidationError("bulk fetch requires items, start_date and end_date")
        items = payload["items"]
        if not isinstance(items, list) or any(
            not isinstance(item, dict)
            or set(item) - {"symbol", "exchange"}
            or not isinstance(item.get("symbol"), str)
            or not item["symbol"].strip()
            or item.get("exchange", "NSE") != "NSE"
            for item in items
        ):
            raise DomainValidationError(
                "bulk fetch items must contain a symbol and supported exchange"
            )
        try:
            start_date = date.fromisoformat(payload["start_date"])
            end_date = date.fromisoformat(payload["end_date"])
        except (TypeError, ValueError, KeyError) as exc:
            raise DomainValidationError("bar fetch dates must be ISO dates") from exc
        if start_date > end_date or end_date - start_date > timedelta(days=1999):
            raise DomainValidationError("bar fetch range must be at most 2000 calendar days")

        current_isins = self._current_history_isins()
        for item in items:
            instrument = self.repository.instrument(item["symbol"], item.get("exchange", "NSE"))
            self._history_context(instrument, start_date, end_date, current_isins=current_isins)

        results: list[dict[str, Any]] = []
        total, processed, written_count = len(items), 0, 0

        def checkpoint():
            if hasattr(context, "checkpoint"):
                context.checkpoint(
                    progress={
                        "stage": "bulk_fetch",
                        "current": processed,
                        "total": total,
                        "written_bars": written_count,
                        "message": f"Processed {processed} of {total} history requests",
                    }
                )

        checkpoint()
        if items:
            provider = KiteHistoricalBarsProvider(self._client())

        def fetch(item):
            try:
                instrument = self.repository.instrument(item["symbol"], item.get("exchange", "NSE"))
                instrument_id = str(instrument["instrument_id"])
                if self.repository.has_coverage(instrument_id, start_date, end_date, "kite"):
                    return {"skipped": True, "instrument_id": instrument_id}
                token = str(instrument["provider_token"])
                bars, raw_records, quality_events = provider.get_bars_with_quality(
                    token,
                    start_date,
                    end_date,
                    symbol=item["symbol"],
                    isin=str(instrument["isin"]),
                )
                return {
                    "skipped": False,
                    "instrument_id": instrument_id,
                    "token": token,
                    "fetched": bars,
                    "raw_records": raw_records,
                    "quality_events": quality_events,
                }
            except (
                DomainValidationError,
                KiteException,
                RequestException,
                OSError,
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
                return {"error": sanitize_error(exc)}

        def persist(item, data):
            nonlocal written_count
            symbol, exchange = item["symbol"], item.get("exchange", "NSE")
            if "error" in data:
                return {"symbol": symbol, "status": "error", "reason": data["error"]}
            if data["skipped"]:
                return {"symbol": symbol, "status": "skipped"}
            instrument_id = data["instrument_id"]
            if not data["fetched"]:
                for quality_event in data.get("quality_events", []):
                    event_date = date.fromisoformat(str(quality_event["as_of_date"]))
                    self.repository.resolve_quality_events(
                        instrument_id,
                        event_date,
                        "provider_ohlc_source_unresolved",
                        {"method": quality_event["check_type"], **quality_event},
                    )
                    self.repository.record_quality_event(
                        instrument_id,
                        event_date,
                        str(quality_event["check_type"]),
                        str(quality_event["severity"]),
                        dict(quality_event),
                    )
                self.repository.record_fetch_coverage(
                    instrument_id, start_date, end_date, provider="kite", bar_count=0
                )
                return {"symbol": symbol, "status": "empty"}
            bars = tuple(
                NormalizedBar(
                    instrument_id,
                    bar.as_of_date,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.traded_value,
                )
                for bar in data["fetched"]
            )
            _raw, normalized = ingest_market_bars(
                self.publisher,
                "kite",
                bars,
                source_request={
                    "symbol": symbol,
                    "exchange": exchange,
                    "provider_token": data["token"],
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
                raw_payload=(
                    {
                        "kite_records": data["raw_records"],
                        "quality_events": data["quality_events"],
                    }
                    if data["quality_events"] else None
                ),
                provider_version="kiteconnect-v5",
                quality=(
                    QualityStatus.PARTIAL
                    if data["quality_events"]
                    else QualityStatus.COMPLETE
                ),
            )
            self.repository.upsert_bars(instrument_id, bars, normalized.artifact_id)
            self.repository.record_fetch_coverage(
                instrument_id, start_date, end_date, provider="kite", bar_count=len(bars)
            )
            for quality_event in data["quality_events"]:
                event_date = date.fromisoformat(str(quality_event["as_of_date"]))
                resolution = {
                    "method": quality_event["check_type"],
                    "source_artifact_id": _raw.artifact_id,
                    "normalized_artifact_id": normalized.artifact_id,
                    **quality_event,
                }
                self.repository.resolve_quality_events(
                    instrument_id,
                    event_date,
                    "provider_ohlc_source_unresolved",
                    resolution,
                )
                self.repository.record_quality_event(
                    instrument_id,
                    event_date,
                    str(quality_event["check_type"]),
                    str(quality_event["severity"]),
                    {**quality_event, "raw_artifact_id": _raw.artifact_id,
                     "normalized_artifact_id": normalized.artifact_id},
                )
            written_count += len(bars)
            return {
                "symbol": symbol,
                "status": "fetched",
                "bar_count": len(bars),
                "quality_events": len(data["quality_events"]),
            }

        # Submit at most ten reads, replenishing only after a checkpoint. A
        # cancelled job never leaves the full universe queued at the provider.
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            remaining = iter(items)
            pending = {}

            def replenish():
                while len(pending) < 10:
                    item = next(remaining, None)
                    if item is None:
                        break
                    pending[executor.submit(fetch, item)] = item

            try:
                replenish()
                while pending:
                    done, _ = concurrent.futures.wait(
                        pending, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                    checkpoint()
                    for future in done:
                        item = pending.pop(future)
                        data = future.result()
                        checkpoint()
                        results.append(persist(item, data))
                        processed += 1
                        checkpoint()
                    replenish()
            finally:
                for future in pending:
                    future.cancel()
        checkpoint()
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "requested": total,
            "processed": processed,
            "written_bars": written_count,
            "failed": sum(item["status"] == "error" for item in results),
            "results": sorted(results, key=lambda item: str(item["symbol"])),
        }
