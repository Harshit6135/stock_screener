"""Optional YFinance bridge used for legacy universe and benchmark compatibility."""

from datetime import date
from typing import Any

from src.platform_kernel import DomainValidationError


def download_daily_bars(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    """Return normalized OHLCV rows when yfinance is installed.

    The dependency is intentionally optional: provider-backed v4 deployments can
    omit it, while local migrations can install yfinance without changing v4's
    core provider contracts.
    """
    try:
        import yfinance as yf  # type: ignore[import-not-found]
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
