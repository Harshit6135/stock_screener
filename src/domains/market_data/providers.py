"""Rate-limited market-data adapters around injected provider clients."""

import csv
import hashlib
import io
import requests
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from threading import Lock
from time import monotonic, sleep
from typing import Any

from src.platform_kernel import DomainValidationError

from .api import NormalizedBar


class _ProviderThrottle:
    def __init__(
        self, requests_per_second: float, sleeper: Callable[[float], None] = sleep
    ) -> None:
        if requests_per_second <= 0:
            raise DomainValidationError("provider rate must be positive")
        self.interval, self.sleeper, self._last_request = 1.0 / requests_per_second, sleeper, 0.0
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self.interval - (monotonic() - self._last_request)
            if delay > 0:
                self.sleeper(delay)
            self._last_request = monotonic()


class NseHistoricalBhavcopyProvider:
    """Read official NSE daily archives to verify inconsistent provider candles."""

    def __init__(self, *, requests_per_second: float = 1.0):
        if requests_per_second <= 0:
            raise DomainValidationError("provider rate must be positive")
        self.interval = 1.0 / requests_per_second
        self._last_request = 0.0
        self._lock = Lock()
        self._cache: dict[
            date, tuple[dict[str, list[dict[str, str]]], dict[str, object]]
        ] = {}

    def equity_row(
        self, as_of_date: date, isin: str
    ) -> tuple[dict[str, str] | None, dict[str, object]]:
        if not isinstance(as_of_date, date) or not isinstance(isin, str) or len(isin) < 9:
            raise DomainValidationError("NSE history identity is invalid")
        with self._lock:
            if as_of_date in self._cache:
                rows_by_isin, evidence = self._cache[as_of_date]
                matches = rows_by_isin.get(isin[:9], [])
                if len(matches) > 1:
                    raise DomainValidationError("NSE daily archive has ambiguous instrument rows")
                return (dict(matches[0]) if matches else None), dict(evidence)

            delay = self.interval - (monotonic() - self._last_request)
            if delay > 0:
                sleep(delay)
            month = as_of_date.strftime("%b").upper()
            filename = f"cm{as_of_date:%d}{month}{as_of_date:%Y}bhav.csv.zip"
            url = f"https://archives.nseindia.com/content/historical/EQUITIES/{as_of_date:%Y}/{month}/{filename}"
            try:
                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/128 Safari/537.36",
                        "Referer": "https://www.nseindia.com/",
                    },
                    timeout=30,
                )
                self._last_request = monotonic()
                if response.status_code == 404:
                    evidence = {"url": url, "http_status": 404, "sha256": None}
                    self._cache[as_of_date] = ({}, evidence)
                    return None, dict(evidence)
                response.raise_for_status()
                checksum = hashlib.sha256(response.content).hexdigest()
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
                    if len(csv_names) != 1:
                        raise DomainValidationError("NSE daily archive contents are invalid")
                    with archive.open(csv_names[0]) as source:
                        reader = csv.DictReader(
                            line.decode("latin1") for line in source
                        )
                        rows_by_isin: dict[str, list[dict[str, str]]] = {}
                        for record in reader:
                            normalized = {
                                str(key).strip().upper(): str(value or "").strip()
                                for key, value in record.items()
                            }
                            if normalized.get("SERIES") == "EQ":
                                rows_by_isin.setdefault(normalized.get("ISIN", "")[:9], []).append(normalized)
                matches = rows_by_isin.get(isin[:9], [])
                if len(matches) > 1:
                    raise DomainValidationError("NSE daily archive has ambiguous instrument rows")
                row = matches[0] if matches else None
                evidence = {"url": url, "http_status": response.status_code, "sha256": checksum}
                self._cache[as_of_date] = (rows_by_isin, evidence)
                return row, dict(evidence)
            except requests.RequestException as exc:
                raise DomainValidationError("official NSE daily history request failed") from exc
            except (zipfile.BadZipFile, csv.Error, OSError) as exc:
                raise DomainValidationError("official NSE daily archive could not be read") from exc


class KiteHistoricalBarsProvider:
    def __init__(
        self,
        client: Any,
        *,
        requests_per_second: float = 3.0,
        sleeper: Callable[[float], None] = sleep,
        nse_daily: NseHistoricalBhavcopyProvider | None = None,
    ):
        self.client, self._throttle = client, _ProviderThrottle(requests_per_second, sleeper)
        self.nse_daily = nse_daily or NseHistoricalBhavcopyProvider()

    def get_bars(
        self, instrument_id: str, start_date: date, end_date: date
    ) -> tuple[NormalizedBar, ...]:
        bars, _raw_records, _quality_events = self.get_bars_with_quality(
            instrument_id, start_date, end_date
        )
        return bars

    def get_bars_with_quality(
        self,
        instrument_id: str,
        start_date: date,
        end_date: date,
        *,
        symbol: str | None = None,
        isin: str | None = None,
    ) -> tuple[tuple[NormalizedBar, ...], tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
        if (not isinstance(instrument_id, str) or not instrument_id.strip()
                or not isinstance(start_date, date) or not isinstance(end_date, date)
                or start_date > end_date):
            raise DomainValidationError("historical provider request is invalid")
        try:
            token = int(instrument_id)
        except ValueError as exc:
            raise DomainValidationError("historical provider token must be a positive integer") from exc
        if token <= 0:
            raise DomainValidationError("historical provider token must be a positive integer")
        self._throttle.wait()
        records = self.client.historical_data(token, start_date, end_date, interval="day")
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
            raise DomainValidationError("historical provider response must contain records")
        bars = []
        raw_records = []
        quality_events = []
        seen_dates: dict[date, tuple[str, str, str, str, str]] = {}
        for record in records:
            if not isinstance(record, Mapping):
                raise DomainValidationError("historical provider record is invalid")
            try:
                timestamp = record["date"]
                day = timestamp.date() if isinstance(timestamp, datetime) else timestamp
                if isinstance(day, str):
                    day = date.fromisoformat(day)
                if not isinstance(day, date) or not start_date <= day <= end_date:
                    raise DomainValidationError("historical provider dates are invalid or duplicated")
                signature = tuple(
                    str(record[key])
                    for key in ("open", "high", "low", "close", "volume")
                )
                if day in seen_dates:
                    if seen_dates[day] != signature:
                        raise DomainValidationError(
                            "historical provider dates are invalid or duplicated"
                        )
                    quality_events.append({
                        "as_of_date": day.isoformat(),
                        "check_type": "identical_duplicate_provider_bar_ignored",
                        "severity": "WARNING",
                        "reason": "provider repeated an identical daily OHLCV row",
                    })
                    raw_records.append(dict(record))
                    continue
                volume = Decimal(str(record["volume"]))
                if isinstance(record["volume"], bool) or not volume.is_finite() or volume < 0 or volume != volume.to_integral_value():
                    raise DomainValidationError("historical provider volume must be a non-negative integer")
                open_price = Decimal(str(record["open"]))
                high_price = Decimal(str(record["high"]))
                low_price = Decimal(str(record["low"]))
                close_price = Decimal(str(record["close"]))
                # Kite can emit an all-zero daily placeholder before an NSE
                # instrument began trading. It is not a price bar and must
                # neither fail the full history run nor become stored data.
                prices = (open_price, high_price, low_price, close_price)
                if all(price == 0 for price in prices) or (
                    volume == 0 and any(price <= 0 for price in prices)
                ):
                    quality_events.append(
                        {
                            "as_of_date": day.isoformat(),
                            "check_type": "provider_zero_price_placeholder_omitted",
                            "severity": "WARNING",
                            "reason": "provider returned a non-positive pre-listing placeholder",
                        }
                    )
                    raw_records.append(dict(record))
                    seen_dates[day] = signature
                    continue
                try:
                    bar = NormalizedBar(
                        instrument_id, day, open_price, high_price, low_price,
                        close_price, int(volume)
                    )
                except DomainValidationError as exc:
                    if str(exc) != "normalized bar OHLC values are inconsistent":
                        raise DomainValidationError(
                            "historical provider OHLCV values are invalid on "
                            f"{day.isoformat()}: {exc}"
                        ) from exc
                    if not symbol or not isin:
                        raise DomainValidationError(
                            "historical provider OHLCV values are inconsistent on "
                            f"{day.isoformat()} (open={open_price}, high={high_price}, "
                            f"low={low_price}, close={close_price})"
                        ) from exc
                    nse_row, source_evidence = self.nse_daily.equity_row(day, isin)
                    raw_record = {
                        "open": str(open_price), "high": str(high_price),
                        "low": str(low_price), "close": str(close_price),
                        "volume": str(int(volume)),
                    }
                    if nse_row is None:
                        if volume == 0:
                            quality_events.append({
                                "as_of_date": day.isoformat(),
                                "check_type": "provider_zero_volume_row_omitted",
                                "severity": "WARNING",
                                "reason": "no official NSE equity row and provider volume is zero",
                                "kite_ohlcv": raw_record,
                                "nse_source": source_evidence,
                            })
                            raw_records.append(dict(record))
                            seen_dates[day] = signature
                            continue
                        raise DomainValidationError(
                            "historical provider OHLCV values are inconsistent on "
                            f"{day.isoformat()} and no official NSE row matched {symbol}"
                        ) from exc
                    try:
                        nse_prices = {
                            key: Decimal(str(nse_row[field]))
                            for key, field in (
                                ("open", "OPEN"), ("high", "HIGH"),
                                ("low", "LOW"), ("close", "CLOSE"),
                            )
                        }
                        nse_volume = Decimal(str(nse_row["TOTTRDQTY"]))
                        if any(not value.is_finite() or value <= 0 for value in nse_prices.values()):
                            raise ValueError("NSE OHLC prices are invalid")
                        ratios = [
                            source / nse_prices[key]
                            for key, source in (
                                ("open", open_price), ("high", high_price), ("low", low_price)
                            )
                        ]
                        ordered_ratios = sorted(ratios)
                        factor = ordered_ratios[len(ordered_ratios) // 2]
                        if any(abs(value / factor - 1) > Decimal("0.01") for value in ratios):
                            raise ValueError("provider and NSE OHLC adjustment factors differ by over 1%")
                        expected_volume = nse_volume / factor
                        if (expected_volume <= 0 or
                                abs(Decimal(int(volume)) / expected_volume - 1) > Decimal("0.02")):
                            raise ValueError("provider and NSE adjusted volumes differ by over 2%")
                        adjusted = {key: value * factor for key, value in nse_prices.items()}
                        bar = NormalizedBar(
                            instrument_id, day, adjusted["open"], adjusted["high"],
                            adjusted["low"], adjusted["close"], int(volume)
                        )
                    except (KeyError, InvalidOperation, TypeError, ValueError, DomainValidationError) as source_error:
                        raise DomainValidationError(
                            "official NSE row could not validate inconsistent Kite OHLC on "
                            f"{day.isoformat()}: {source_error}"
                        ) from source_error
                    quality_events.append({
                        "as_of_date": day.isoformat(),
                        "check_type": "provider_ohlc_reconciled_from_nse",
                        "severity": "WARNING",
                        "reason": "official NSE OHLC scaled to the provider price basis using matching open/high/low and volume",
                        "kite_ohlcv": raw_record,
                        "nse_row": {
                            key: value for key, value in nse_row.items() if key != "SYMBOL"
                        },
                        "nse_source": source_evidence,
                        "adjustment_factor": str(factor),
                        "stored_ohlc": {key: str(value) for key, value in adjusted.items()},
                    })
            except DomainValidationError:
                raise
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise DomainValidationError("historical provider OHLCV record is invalid") from exc
            bars.append(bar)
            raw_records.append(dict(record))
            seen_dates[day] = signature
        return (
            tuple(sorted(bars, key=lambda bar: bar.as_of_date)),
            tuple(raw_records),
            tuple(quality_events),
        )


class KiteInstrumentProvider:
    def __init__(
        self,
        client: Any,
        exchange: str | None = None,
        *,
        requests_per_second: float = 3.0,
        sleeper: Callable[[float], None] = sleep,
    ):
        self.client, self.exchange = client, exchange
        self._throttle = _ProviderThrottle(requests_per_second, sleeper)

    def get_instruments(self) -> Sequence[object]:
        self._throttle.wait()
        return tuple(
            self.client.instruments(self.exchange) if self.exchange else self.client.instruments()
        )


class KiteQuoteProvider:
    def __init__(
        self,
        client: Any,
        *,
        requests_per_second: float = 3.0,
        sleeper: Callable[[float], None] = sleep,
    ):
        self.client = client
        self._throttle = _ProviderThrottle(requests_per_second, sleeper)

    def get_quote(self, instrument_id: str) -> object:
        self._throttle.wait()
        response = self.client.ohlc([instrument_id])
        try:
            return response[instrument_id]
        except KeyError as exc:
            raise DomainValidationError(f"quote provider did not return {instrument_id}") from exc
