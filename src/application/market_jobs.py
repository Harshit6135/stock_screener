"""Kite instrument synchronization and bounded daily history ingestion."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from kiteconnect import KiteConnect  # type: ignore[import-untyped]

from src.application.ingestion import ingest_market_bars
from src.application.kite_auth import KiteCredentials
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.providers import KiteHistoricalBarsProvider
from src.application.publication import ArtifactPublisher
from src.application.sqlite import sqlite_connection
from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError

NSE_INDEX_SYMBOLS = frozenset(
    {"NIFTY 50", "NIFTY 100", "NIFTY BANK", "NIFTY MIDCAP 50", "NIFTY 500", "INDIA VIX"}
)
BSE_INDEX_SYMBOLS = frozenset({"SENSEX", "BANKEX"})


class KiteMarketJobs:
    def __init__(
        self,
        repository: MarketRepository,
        publisher: ArtifactPublisher,
        credentials: KiteCredentials | None,
        token_path: str | Path,
        nse_csv_path: str | Path,
        bse_csv_path: str | Path | None = None,
        legacy_market_path: str | Path | None = None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.credentials = credentials
        self.token_path = Path(token_path)
        self.nse_csv_path = Path(nse_csv_path)
        self.bse_csv_path = Path(bse_csv_path) if bse_csv_path else None
        self.legacy_market_path = Path(legacy_market_path) if legacy_market_path else None

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

    def sync_instruments(self, payload: dict[str, Any]) -> dict[str, object]:
        if payload:
            raise DomainValidationError("instrument sync takes no payload")
        with self.nse_csv_path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise DomainValidationError("NSE reference file is empty")
            reader.fieldnames = [name.strip() for name in reader.fieldnames]
            listing_rows = [
                (row["SYMBOL"].strip(), row["ISIN NUMBER"].strip())
                for row in reader
                if row.get("SYMBOL")
                and row.get("ISIN NUMBER")
                and row.get("SERIES", "").strip() == "EQ"
            ]
        duplicate_symbols = {
            symbol
            for symbol, count in Counter(symbol for symbol, _ in listing_rows).items()
            if count > 1
        }
        listing = {symbol: isin for symbol, isin in listing_rows if symbol not in duplicate_symbols}
        if not listing:
            raise DomainValidationError("NSE reference file has no EQ instruments")
        provider_records = self._client().instruments("NSE")
        observed_on = datetime.now(UTC).date()
        records: list[TrackedInstrument] = []
        seen: set[str] = set()
        for record in provider_records:
            symbol = str(record.get("tradingsymbol", ""))
            isin = listing.get(symbol)
            if isin and record.get("instrument_type") == "EQ":
                instrument_id = str(uuid5(NAMESPACE_URL, f"NSE:{isin}"))
            elif symbol in NSE_INDEX_SYMBOLS:
                isin = f"INDEX:{symbol}"
                instrument_id = str(uuid5(NAMESPACE_URL, f"NSE:INDEX:{symbol}"))
            else:
                continue
            if instrument_id in seen:
                raise DomainValidationError("Kite instrument master contains duplicate identity")
            seen.add(instrument_id)
            records.append(
                TrackedInstrument(
                    instrument_id,
                    isin,
                    symbol,
                    "NSE",
                    str(record["instrument_token"]),
                    observed_on,
                )
            )
        if not records:
            raise DomainValidationError("Kite returned no matching NSE instruments")
        token_changes = self._token_changes(records)
        fingerprint = hashlib.sha256(
            json.dumps(
                sorted((item.instrument_id, item.symbol, item.provider_token) for item in records)
            ).encode("utf-8")
        ).hexdigest()
        snapshot_id = str(uuid5(NAMESPACE_URL, f"kite-nse-instruments:{observed_on}:{fingerprint}"))
        if not self.publisher.catalog.has(snapshot_id):
            self.publisher.publish_json(
                "reference/kite_instruments",
                snapshot_id,
                {
                    "snapshot_id": snapshot_id,
                    "observed_on": observed_on,
                    "source": "Kite NSE instrument master + NSE EQ CSV",
                    "matched_count": len(records),
                    "instruments": [record.__dict__ for record in records],
                },
            )
        self.repository.upsert_instruments(records)
        reconciliation_id = self._publish_reconciliation(
            "NSE", observed_on, snapshot_id, listing_rows, provider_records, records, token_changes
        )
        return {
            "artifact_id": snapshot_id,
            "reconciliation_artifact_id": reconciliation_id,
            "matched_count": len(records),
            "observed_on": observed_on.isoformat(),
        }

    def sync_bse_instruments(self, payload: dict[str, Any]) -> dict[str, object]:
        """Match active BSE equity ISINs and index tokens against Kite's BSE master."""
        if payload:
            raise DomainValidationError("BSE instrument sync takes no payload")
        if self.bse_csv_path is None or not self.bse_csv_path.is_file():
            raise DomainValidationError("BSE reference file is unavailable")
        with self.bse_csv_path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise DomainValidationError("BSE reference file is empty")
            reader.fieldnames = [name.strip() for name in reader.fieldnames]
            listing_rows = [
                (row["Security Id"].strip(), row["ISIN No"].strip())
                for row in reader
                if row.get("Security Id")
                and row.get("ISIN No", "").startswith("IN")
                and row.get("Status", "").strip() == "Active"
                and row.get("Instrument", "").strip() == "Equity"
            ]
        duplicate_symbols = {
            symbol
            for symbol, count in Counter(symbol for symbol, _ in listing_rows).items()
            if count > 1
        }
        listing = {symbol: isin for symbol, isin in listing_rows if symbol not in duplicate_symbols}
        if not listing:
            raise DomainValidationError("BSE reference file has no active equity instruments")
        provider_records = self._client().instruments("BSE")
        observed_on = datetime.now(UTC).date()
        records: list[TrackedInstrument] = []
        seen: set[str] = set()
        for record in provider_records:
            symbol = str(record.get("tradingsymbol", ""))
            isin = listing.get(symbol)
            if isin and record.get("instrument_type") == "EQ":
                instrument_id = str(uuid5(NAMESPACE_URL, f"BSE:{isin}"))
            elif symbol in BSE_INDEX_SYMBOLS:
                isin = f"INDEX:{symbol}"
                instrument_id = str(uuid5(NAMESPACE_URL, f"BSE:INDEX:{symbol}"))
            else:
                continue
            if instrument_id in seen:
                raise DomainValidationError("Kite BSE master contains duplicate identity")
            seen.add(instrument_id)
            records.append(
                TrackedInstrument(
                    instrument_id,
                    isin,
                    symbol,
                    "BSE",
                    str(record["instrument_token"]),
                    observed_on,
                )
            )
        if not records:
            raise DomainValidationError("Kite returned no matching BSE instruments")
        token_changes = self._token_changes(records)
        fingerprint = hashlib.sha256(
            json.dumps(
                sorted((item.instrument_id, item.symbol, item.provider_token) for item in records)
            ).encode("utf-8")
        ).hexdigest()
        snapshot_id = str(uuid5(NAMESPACE_URL, f"kite-bse-instruments:{observed_on}:{fingerprint}"))
        if not self.publisher.catalog.has(snapshot_id):
            self.publisher.publish_json(
                "reference/kite_instruments",
                snapshot_id,
                {
                    "snapshot_id": snapshot_id,
                    "observed_on": observed_on,
                    "source": "Kite BSE instrument master + BSE equity CSV",
                    "matched_count": len(records),
                    "instruments": [record.__dict__ for record in records],
                },
            )
        self.repository.upsert_instruments(records)
        reconciliation_id = self._publish_reconciliation(
            "BSE", observed_on, snapshot_id, listing_rows, provider_records, records, token_changes
        )
        return {
            "artifact_id": snapshot_id,
            "reconciliation_artifact_id": reconciliation_id,
            "matched_count": len(records),
            "observed_on": observed_on.isoformat(),
        }

    def _token_changes(self, records: list[TrackedInstrument]) -> list[dict[str, str]]:
        changes = []
        for record in records:
            previous = self.repository.instrument_by_id(record.instrument_id)
            if previous is not None and previous["provider_token"] != record.provider_token:
                changes.append(
                    {
                        "symbol": record.symbol,
                        "instrument_id": record.instrument_id,
                        "previous_token": str(previous["provider_token"]),
                        "provider_token": record.provider_token,
                    }
                )
        return sorted(changes, key=lambda item: item["symbol"])

    def _publish_reconciliation(
        self,
        exchange: str,
        observed_on: date,
        snapshot_id: str,
        listing_rows: list[tuple[str, str]],
        provider_records: list[dict[str, Any]],
        matched: list[TrackedInstrument],
        token_changes: list[dict[str, str]],
    ) -> str:
        source_symbols = Counter(symbol for symbol, _ in listing_rows)
        matched_symbols = {item.symbol for item in matched}
        matched_pairs = {(item.symbol, item.provider_token) for item in matched}
        provider_symbols = {str(item.get("tradingsymbol", "")) for item in provider_records}
        matched_ids = {item.instrument_id for item in matched}
        coverage = []
        offset = 0
        while True:
            page = self.repository.coverage(exchange=exchange, limit=500, offset=offset)
            coverage.extend(
                {
                    "instrument_id": row["instrument_id"],
                    "symbol": row["symbol"],
                    "bar_count": row["bar_count"],
                    "latest_date": row["latest_date"],
                }
                for row in page
                if row["instrument_id"] in matched_ids
            )
            if len(page) < 500:
                break
            offset += len(page)
        payload: dict[str, Any] = {
            "exchange": exchange,
            "observed_on": observed_on.isoformat(),
            "instrument_snapshot_id": snapshot_id,
            "source_listing_count": len(listing_rows),
            "provider_record_count": len(provider_records),
            "matched_count": len(matched),
            "duplicate_source_symbols": sorted(
                symbol for symbol, count in source_symbols.items() if count > 1
            ),
            "unmatched_source_symbols": [
                {
                    "symbol": symbol,
                    "isin": isin,
                    "reason": "duplicate_source_symbol"
                    if source_symbols[symbol] > 1
                    else "absent_from_provider"
                    if symbol not in provider_symbols
                    else "provider_record_not_eligible",
                }
                for symbol, isin in sorted(set(listing_rows))
                if symbol not in matched_symbols
            ],
            "excluded_provider_records": [
                {
                    "symbol": str(item.get("tradingsymbol", "")),
                    "provider_token": str(item.get("instrument_token", "")),
                }
                for item in provider_records
                if (str(item.get("tradingsymbol", "")), str(item.get("instrument_token", "")))
                not in matched_pairs
            ],
            "token_changes": token_changes,
            "bar_coverage": sorted(coverage, key=lambda item: str(item["symbol"])),
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        artifact_id = str(uuid5(NAMESPACE_URL, f"reference-reconciliation:{fingerprint}"))
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "reference/reconciliations", artifact_id, payload, upstream_ids=(snapshot_id,)
            )
        return artifact_id

    def fetch_index_quotes(self, payload: dict[str, Any]) -> dict[str, object]:
        """Fetch a single timestamped Kite quote snapshot for all tracked indices."""
        if payload:
            raise DomainValidationError("index quote refresh takes no payload")
        tracked = []
        for exchange, symbols in (("NSE", NSE_INDEX_SYMBOLS), ("BSE", BSE_INDEX_SYMBOLS)):
            for symbol in sorted(symbols):
                try:
                    instrument = self.repository.instrument(symbol, exchange)
                except DomainValidationError:
                    continue
                tracked.append((exchange, symbol, instrument))
        if not tracked:
            raise DomainValidationError("no index identities are synchronized")
        raw = self._client().ohlc([f"{exchange}:{symbol}" for exchange, symbol, _ in tracked])
        if not isinstance(raw, dict):
            raise DomainValidationError("Kite index quote response is invalid")
        observed_at = datetime.now(UTC).isoformat()
        quotes: list[dict[str, object]] = []
        for exchange, symbol, instrument in tracked:
            item = raw.get(f"{exchange}:{symbol}")
            if not isinstance(item, dict):
                continue
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

    def fetch_bars(self, payload: dict[str, Any]) -> dict[str, object]:
        symbol = payload.get("symbol")
        exchange = payload.get("exchange", "NSE")
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(exchange, str)
            or exchange not in {"NSE", "BSE"}
            or set(payload)
            not in (
                {"symbol", "start_date", "end_date"},
                {"symbol", "exchange", "start_date", "end_date"},
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
        if start_date > end_date or end_date - start_date > timedelta(days=365):
            raise DomainValidationError("bar fetch range must be at most 365 days")
        instrument = self.repository.instrument(symbol, exchange)
        instrument_id = str(instrument["instrument_id"])
        fetched = KiteHistoricalBarsProvider(self._client()).get_bars(
            str(instrument["provider_token"]), start_date, end_date
        )
        if not fetched:
            raise DomainValidationError("Kite returned no bars for the requested range")
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
            },
            provider_version="kiteconnect-v5",
        )
        self.repository.upsert_bars(instrument_id, bars, normalized.artifact_id)
        return {
            "raw_artifact_id": raw.artifact_id,
            "artifact_id": normalized.artifact_id,
            "symbol": symbol,
            "exchange": exchange,
            "bar_count": len(bars),
            "first_date": bars[0].as_of_date.isoformat(),
            "last_date": bars[-1].as_of_date.isoformat(),
        }

    def import_v3_bars(self, payload: dict[str, Any]) -> dict[str, object]:
        """Import one symbol's legacy OHLCV as immutable evidence without writing v3."""
        symbol = payload.get("symbol")
        if (
            not isinstance(symbol, str)
            or not symbol
            or set(payload) != {"symbol", "start_date", "end_date"}
        ):
            raise DomainValidationError("v3 bar import requires symbol, start_date and end_date")
        try:
            start_date = date.fromisoformat(payload["start_date"])
            end_date = date.fromisoformat(payload["end_date"])
        except (TypeError, ValueError, KeyError) as exc:
            raise DomainValidationError("v3 bar import dates must be ISO dates") from exc
        if start_date > end_date or end_date - start_date > timedelta(days=365):
            raise DomainValidationError("v3 bar import range must be at most 365 days")
        if self.legacy_market_path is None or not self.legacy_market_path.is_file():
            raise DomainValidationError("v3 market database is unavailable")
        instrument = self.repository.instrument(symbol)
        with sqlite_connection(
            self.legacy_market_path, read_only=True, row_factory=True
        ) as connection:
            identity_rows = connection.execute(
                "SELECT DISTINCT isin FROM master_stocks WHERE nse_symbol = ?",
                (symbol,),
            ).fetchall()
            if len(identity_rows) != 1 or identity_rows[0]["isin"] != instrument["isin"]:
                raise DomainValidationError("v3 and current NSE instrument ISIN do not match")
            rows = connection.execute(
                """SELECT date, open, high, low, close, volume FROM market_data
                   WHERE tradingsymbol = ? AND date BETWEEN ? AND ? ORDER BY date""",
                (symbol, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        bars = tuple(
            NormalizedBar(
                str(instrument["instrument_id"]),
                date.fromisoformat(row["date"]),
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                int(row["volume"]),
            )
            for row in rows
        )
        if not bars:
            raise DomainValidationError("v3 market database has no bars in requested range")
        raw, normalized = ingest_market_bars(
            self.publisher,
            "v3-sqlite",
            bars,
            source_request={
                "source_database": "legacy market_data.db",
                "symbol": symbol,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            provider_version="v3-dabff59",
        )
        self.repository.upsert_bars(str(instrument["instrument_id"]), bars, normalized.artifact_id)
        return {
            "raw_artifact_id": raw.artifact_id,
            "artifact_id": normalized.artifact_id,
            "symbol": symbol,
            "bar_count": len(bars),
            "first_date": bars[0].as_of_date.isoformat(),
            "last_date": bars[-1].as_of_date.isoformat(),
        }
