"""Optional YFinance bridge for universe enrichment and benchmark support."""

import logging
import time
from datetime import date
from typing import Any

from src.platform_kernel import DomainValidationError

logger = logging.getLogger(__name__)


def download_daily_bars(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    """Return normalized OHLCV rows when yfinance is installed.

    The dependency is intentionally optional: provider-backed v4 deployments can
    omit it, while local migrations can install yfinance without changing v4's
    core provider contracts.
    """
    try:
        import yfinance as yf  # type: ignore[import-untyped]
    except ImportError as exc:
        raise DomainValidationError("yfinance is not installed") from exc
    frame = yf.download(symbol, start=start.isoformat(), end=end.isoformat(), auto_adjust=False, progress=False)
    if frame is None or frame.empty:
        raise DomainValidationError(f"yfinance returned no data for {symbol}")
    if hasattr(frame.columns, "levels") and len(frame.columns.levels) > 1:
        frame.columns = frame.columns.get_level_values(0)
    rows = []
    for index, row in frame.iterrows():
        rows.append({
            "as_of_date": index.date().isoformat() if hasattr(index, "date") else str(index)[:10],
            "open": float(row["Open"]), "high": float(row["High"]),
            "low": float(row["Low"]), "close": float(row["Close"]),
            "volume": int(row["Volume"]), "snapshot_id": f"yfinance:{symbol}:{index.date().isoformat()}",
        })
    return rows


def fetch_symbol_enrichment(
    symbol: str,
    exchange: str = "NSE",
    scrip_code: str | None = None,
    request_delay_seconds: float = 0.5,
) -> dict[str, Any]:
    """Fetch metadata and quote info from yfinance for a single stock."""
    try:
        import yfinance as yf  # type: ignore[import-untyped]
        from curl_cffi.requests.exceptions import RequestException
        from yfinance.exceptions import YFException  # type: ignore[import-untyped]
    except ImportError as exc:
        raise DomainValidationError("yfinance is not installed") from exc
    if request_delay_seconds < 0:
        raise DomainValidationError("request_delay_seconds must not be negative")
    candidates = [f"{symbol}.NS"] if exchange.upper() == "NSE" else [f"{symbol}.BO"]
    if exchange.upper() == "BSE" and scrip_code and str(scrip_code).strip() != str(symbol).strip():
        candidates.append(f"{str(scrip_code).strip()}.BO")
    info: dict[str, Any] = {}
    for index, ticker_str in enumerate(candidates):
        if index:
            time.sleep(request_delay_seconds)
        try:
            ticker = yf.Ticker(ticker_str)
            info = getattr(ticker, "info", None) or {}
        except (YFException, RequestException, OSError, TypeError, ValueError) as exc:
            logger.debug("yfinance enrichment failed for %s", ticker_str, exc_info=exc)
            info = {}
        if info.get("marketCap"):
            break
    if request_delay_seconds and candidates:
        time.sleep(request_delay_seconds)
    if not info.get("marketCap"):
        raise DomainValidationError(f"yfinance returned no market cap for {symbol} on {exchange}")
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or 0.0
    market_cap = info.get("marketCap") or 0.0
    return {
        "symbol": symbol,
        "exchange": exchange,
        "company_name": info.get("shortName") or info.get("longName") or symbol,
        "sector": info.get("sector", "Unknown"),
        "industry": info.get("industry", "Unknown"),
        "market_cap": float(market_cap),
        "current_price": float(price),
        "eligible": float(market_cap) > 5_000_000_000,
    }
