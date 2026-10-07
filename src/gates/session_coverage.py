"""Coverage diagnostics from completed NSE benchmark sessions and as-of membership."""

from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection


class CompletedSessionCoverage:
    def __init__(self, market, benchmark_symbols, clock=None):
        self.market = market
        self.benchmark_symbols = frozenset(benchmark_symbols)
        self.clock = clock or (lambda: datetime.now(ZoneInfo("Asia/Kolkata")).date())

    def read(self, start, end):
        if (not isinstance(start, date) or isinstance(start, datetime)
                or not isinstance(end, date) or isinstance(end, datetime) or start > end):
            raise DomainValidationError("session coverage requires an ordered date range")
        today = self.clock()
        with sqlite_connection(self.market.path, read_only=True, row_factory=True) as connection:
            connection.execute("BEGIN")
            sessions = [str(row[0]) for row in connection.execute(
                """SELECT DISTINCT b.as_of_date FROM market_bars b
                   JOIN reference_instruments i ON i.instrument_id=b.instrument_id
                   WHERE i.exchange='NSE' AND i.symbol='NIFTY 500'
                   AND b.as_of_date BETWEEN ? AND ? ORDER BY b.as_of_date""",
                (start.isoformat(), end.isoformat()))]
            snapshots = [dict(row) for row in connection.execute(
                "SELECT snapshot_id, snapshot_date FROM universe_snapshots WHERE index_name='NIFTY 500' ORDER BY snapshot_date")]
            members = defaultdict(list)
            for row in connection.execute("""SELECT m.snapshot_id, m.isin, m.symbol FROM universe_snapshot_members m
                JOIN universe_snapshots s ON s.snapshot_id=m.snapshot_id WHERE s.index_name='NIFTY 500'"""):
                members[str(row["snapshot_id"])].append(dict(row))
            identities = [dict(row) for row in connection.execute("SELECT * FROM reference_instruments WHERE exchange='NSE'")]
            bars = {(str(row["instrument_id"]), str(row["as_of_date"])) for row in connection.execute(
                "SELECT instrument_id, as_of_date FROM market_bars WHERE as_of_date BETWEEN ? AND ?",
                (start.isoformat(), end.isoformat()))}
            revisions = {str(row["instrument_id"]): str(row["revision"]) for row in connection.execute(
                "SELECT instrument_id, revision FROM market_history_revisions")}
        complete = [day for day in sessions if day < today.isoformat()]
        report = {"start_date": start.isoformat(), "end_date": end.isoformat(),
                  "completed_before": min(today, end + timedelta(days=1)).isoformat(), "calendar_source": "observed_nse_nifty500",
                  "calendar_status": "AVAILABLE" if complete else "UNAVAILABLE",
                  "observed_session_count": len(complete), "skipped_incomplete_sessions": len(sessions)-len(complete),
                  "membership_status": "AVAILABLE" if snapshots else "UNAVAILABLE",
                  "missing_identities": [], "missing_bars": [], "membership_lineage": []}
        if not complete or not snapshots:
            return {**report, "status": "UNAVAILABLE"}
        by_isin = {str(row["isin"]): row for row in identities}
        by_symbol = {str(row["symbol"]): row for row in identities if str(row["isin"]).startswith("INDEX:")}
        snapshot_dates = [str(item["snapshot_date"]) for item in snapshots]
        expected = defaultdict(list)
        missing_ids = {}
        used = {}
        for day in complete:
            position = bisect_right(snapshot_dates, day)-1
            snapshot = snapshots[max(0, position)]
            snapshot_id = str(snapshot["snapshot_id"])
            used[(snapshot_id, position < 0)] = {"snapshot_id": snapshot_id,
                "snapshot_date": snapshot["snapshot_date"], "earliest_fallback": position < 0}
            required = [(item["symbol"], by_isin.get(str(item["isin"]))) for item in members[snapshot_id]]
            required += [(symbol, by_symbol.get(symbol)) for symbol in sorted(self.benchmark_symbols)]
            for symbol, identity in required:
                if identity is None:
                    missing_ids[(snapshot_id, symbol)] = {"snapshot_id": snapshot_id, "symbol": symbol,
                                                         "reason": "unresolved_instrument_identity"}
                    continue
                expected[(snapshot_id, str(identity["instrument_id"]), str(symbol))].append(day)
        for (snapshot_id, instrument_id, symbol), days in sorted(expected.items()):
            missing = [day for day in days if (instrument_id, day) not in bars]
            if missing:
                report["missing_bars"].append({"instrument_id": instrument_id, "symbol": symbol,
                    "snapshot_id": snapshot_id, "market_revision": revisions.get(instrument_id, "0"),
                    "expected_sessions": len(days), "actual_sessions": len(days)-len(missing),
                    "missing_session_count": len(missing), "missing_session_sample": missing[:20],
                    "last_expected_session": days[-1]})
        report["membership_lineage"] = list(used.values())
        report["missing_identities"] = list(missing_ids.values())
        report["status"] = "PARTIAL" if report["missing_bars"] or missing_ids else "COMPLETE"
        return report

    def record(self, start, end):
        report = self.read(start, end)
        for item in report["missing_bars"]:
            self.market.record_quality_event(item["instrument_id"], date.fromisoformat(item["last_expected_session"]),
                "missing_completed_sessions", "WARNING", {"calendar_source": report["calendar_source"],
                    "start_date": report["start_date"], "end_date": report["end_date"], **item})
        return report
