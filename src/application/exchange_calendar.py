"""Trading calendar derived from observed market data.

The calendar does not import an external holiday list.  Instead it queries
actual ``market_bars`` dates for the benchmark instrument, which are
authoritative because they come from Kite's completed session data.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.application.sqlite import sqlite_connection


class TradingCalendar:
    """Derive actual trading sessions from observed market data."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)

    def sessions(
        self,
        start: date,
        end: date,
        *,
        benchmark_symbol: str = "NIFTY 500",
    ) -> list[date]:
        """Return dates where ``market_bars`` exist for the benchmark.

        Falls back to all distinct bar dates across all instruments when the
        benchmark itself has no data in the requested range.
        """
        with sqlite_connection(self.database, read_only=True, row_factory=True) as conn:
            rows = conn.execute(
                """SELECT DISTINCT mb.as_of_date
                   FROM market_bars mb
                   JOIN reference_instruments ri ON ri.instrument_id = mb.instrument_id
                   WHERE ri.symbol = ?
                   AND mb.as_of_date BETWEEN ? AND ?
                   ORDER BY mb.as_of_date""",
                (benchmark_symbol, start.isoformat(), end.isoformat()),
            ).fetchall()

        if rows:
            return [date.fromisoformat(str(row["as_of_date"])) for row in rows]

        # Fallback: use any instrument's observed dates
        with sqlite_connection(self.database, read_only=True, row_factory=True) as conn:
            rows = conn.execute(
                """SELECT DISTINCT as_of_date
                   FROM market_bars
                   WHERE as_of_date BETWEEN ? AND ?
                   ORDER BY as_of_date""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()

        return [date.fromisoformat(str(row["as_of_date"])) for row in rows]

    def is_trading_day(
        self,
        check_date: date,
        *,
        benchmark_symbol: str = "NIFTY 500",
    ) -> bool:
        """Return whether the given date is an observed trading session."""
        sessions = self.sessions(check_date, check_date, benchmark_symbol=benchmark_symbol)
        return len(sessions) > 0

    def last_session(
        self,
        before: date,
        *,
        benchmark_symbol: str = "NIFTY 500",
    ) -> date | None:
        """Return the most recent trading session strictly before ``before``."""
        with sqlite_connection(self.database, read_only=True, row_factory=True) as conn:
            row = conn.execute(
                """SELECT MAX(mb.as_of_date) AS last_date
                   FROM market_bars mb
                   JOIN reference_instruments ri ON ri.instrument_id = mb.instrument_id
                   WHERE ri.symbol = ? AND mb.as_of_date < ?""",
                (benchmark_symbol, before.isoformat()),
            ).fetchone()

        if row and row["last_date"]:
            return date.fromisoformat(str(row["last_date"]))
        return None
