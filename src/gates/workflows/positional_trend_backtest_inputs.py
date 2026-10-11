"""Gate-owned composite readers for Positional trend replay inputs."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def load_data(
    database: Path, universe_csv: Path, *, end_date: str | None = None, include_be: bool = False
) -> tuple[dict, list[str], dict]:
    if not database.is_file() or not universe_csv.is_file():
        raise ValueError("database and constituent CSV must exist")
    with universe_csv.open(encoding="utf-8-sig", newline="") as stream:
        constituent_rows = list(csv.DictReader(stream))
        accepted_series = {"EQ", "BE"} if include_be else {"EQ"}
        members = {row["ISIN Code"] for row in constituent_rows if row["Series"] in accepted_series}
    if not members:
        raise ValueError("constituent CSV contains no EQ members")
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in members)
        identities = connection.execute(
            f"SELECT instrument_id, isin, symbol, observed_on, exchange FROM reference_instruments "
            f"WHERE exchange='NSE' AND isin IN ({placeholders}) "
            f"ORDER BY isin, observed_on DESC, symbol",
            sorted(members),
        ).fetchall()
        chosen = {}
        chosen_exchanges = {}
        for row in identities:
            if row["isin"] not in chosen:
                chosen[row["isin"]] = (row["instrument_id"], row["symbol"])
                chosen_exchanges[row["isin"]] = row["exchange"]
        if not chosen:
            raise ValueError("no constituent EQ members match NSE reference instruments")
        ids = [item[0] for item in chosen.values()]
        symbols = {item[0]: item[1] for item in chosen.values()}
        placeholders = ",".join("?" for _ in ids)
        cutoff = end_date or datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        rows = connection.execute(
            f"SELECT instrument_id, as_of_date, open, high, low, close, volume "
            f"FROM market_bars WHERE instrument_id IN ({placeholders}) "
            f"AND as_of_date BETWEEN '2021-01-01' AND ? "
            f"ORDER BY instrument_id, as_of_date",
            [*ids, cutoff],
        )
        histories: dict[str, tuple[str, list[dict]]] = {}
        all_sessions = set()
        bar_count = 0
        for row in rows:
            instrument_id = row["instrument_id"]
            if instrument_id not in histories:
                histories[instrument_id] = (symbols[instrument_id], [])
            bar = dict(row)
            histories[instrument_id][1].append(bar)
            all_sessions.add(bar["as_of_date"])
            bar_count += 1
    finally:
        connection.close()
    sessions = sorted(all_sessions)
    coverage = {
        "universe_source": "constituent_csv",
        "universe_csv": universe_csv.name,
        "constituent_eq_count": sum(row["Series"] == "EQ" for row in constituent_rows),
        "included_member_count": len(members),
        "included_series": sorted(accepted_series),
        "matched_isin_count": len(chosen),
        "matched_members_by_exchange": dict(Counter(chosen_exchanges.values())),
        "price_source": "NSE only",
        "instruments_with_bars": len(histories),
        "bar_count": bar_count,
        "session_count": len(sessions),
        "first_session": sessions[0] if sessions else None,
        "last_session": sessions[-1] if sessions else None,
        "missing_isins": sorted(members - chosen.keys()),
        "universe_csv_sha256": hashlib.sha256(universe_csv.read_bytes()).hexdigest(),
        "historical_membership": "current_constituents_applied_backwards",
        "corporate_action_adjustment": "not_applied_per_research_scope",
    }
    return histories, sessions, coverage


def load_market_cap_universe(database: Path, *, end_date: str) -> tuple[dict, list[str], dict]:
    """Use the current NSE universe retrospectively."""
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        members = [
            dict(row)
            for row in connection.execute(
                "SELECT u.*, r.symbol AS current_symbol FROM universe_membership u "
                "JOIN reference_instruments r ON r.instrument_id=u.instrument_id "
                "WHERE u.exchange='NSE' AND u.last_market_cap >= 5000000000 "
                "ORDER BY u.isin"
            )
        ]
        if not members:
            raise ValueError("application market-cap universe is empty")
        symbols = [row["current_symbol"] for row in members]
        if len(set(symbols)) != len(symbols):
            raise ValueError("duplicate symbols across exchanges require explicit identity labels")
        histories = {row["instrument_id"]: (row["current_symbol"], []) for row in members}
        slots = ",".join("?" for _ in histories)
        count = 0
        for row in connection.execute(
            f"SELECT instrument_id, as_of_date, open, high, low, close, volume FROM market_bars "
            f"WHERE instrument_id IN ({slots}) AND as_of_date BETWEEN '2021-01-01' AND ? "
            "ORDER BY instrument_id, as_of_date",
            [*histories, end_date],
        ):
            bar = dict(row)
            instrument_id = bar.pop("instrument_id")
            histories[instrument_id][1].append(bar)
            count += 1
        benchmark = connection.execute(
            "SELECT instrument_id FROM reference_instruments WHERE exchange='NSE' "
            "AND symbol='NIFTY 500' ORDER BY observed_on DESC LIMIT 1"
        ).fetchone()
        if benchmark is None:
            raise ValueError("Nifty 500 benchmark calendar is missing")
        sessions = [
            row[0]
            for row in connection.execute(
                "SELECT as_of_date FROM market_bars WHERE instrument_id=? "
                "AND as_of_date BETWEEN '2021-01-01' AND ? ORDER BY as_of_date",
                (benchmark[0], end_date),
            )
        ]
        coverage = {
            "universe_source": "application_market_cap_universe",
            "minimum_market_cap_crore": 500,
            "members": len(members),
            "members_by_exchange": dict(Counter(row["exchange"] for row in members)),
            "instruments_with_bars": sum(bool(bars) for _, bars in histories.values()),
            "bar_count": count,
            "session_count": len(sessions),
            "calendar": "NIFTY 500 stored sessions",
            "first_session": sessions[0] if sessions else None,
            "last_session": sessions[-1] if sessions else None,
            "membership_snapshot_dates": sorted({row["snapshot_date"] for row in members}),
            "membership_sha256": hashlib.sha256(
                json.dumps(members, sort_keys=True).encode()
            ).hexdigest(),
            "historical_membership": "current_market_cap_members_applied_backwards",
            "corporate_action_adjustment": "not_applied_per_research_scope",
        }
        return histories, sessions, coverage
    finally:
        connection.close()


def load_snapshot_universe(database: Path, *, end_date: str) -> tuple[dict, list[str], dict]:
    """Load every known as-of member, with explicit earliest-snapshot fallback.

    Include one observed session after the requested end solely for exit fills.
    Membership and eligibility always come from the decision session's snapshot.
    """
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        snapshots = [
            dict(row)
            for row in connection.execute(
                """SELECT snapshot_id, snapshot_date, source_hash FROM universe_snapshots
               WHERE index_name='NIFTY 500' ORDER BY snapshot_date"""
            )
        ]
        if not snapshots:
            raise ValueError("Nifty 500 universe snapshot is unavailable")
        relevant = [row for row in snapshots if row["snapshot_date"] <= end_date] or snapshots[:1]
        members = {
            row["snapshot_id"]: {
                str(member[0])
                for member in connection.execute(
                    "SELECT isin FROM universe_snapshot_members WHERE snapshot_id=?",
                    (row["snapshot_id"],),
                )
            }
            for row in relevant
        }
        isins = set().union(*members.values())
        identities = [
            dict(row)
            for row in connection.execute(
                """SELECT instrument_id, isin, symbol FROM reference_instruments
               WHERE exchange='NSE' ORDER BY isin, observed_on DESC, symbol"""
            )
            if row["isin"] in isins
        ]
        chosen = {}
        for row in identities:
            chosen.setdefault(row["isin"], (str(row["instrument_id"]), str(row["symbol"])))
        if not chosen:
            raise ValueError("no snapshot members match NSE reference instruments")
        # Benchmark sessions establish the next session even when an excluded
        # instrument has a missing open. Never choose a later price for it.
        benchmark_sessions = [
            str(row[0])
            for row in connection.execute(
                """SELECT DISTINCT b.as_of_date FROM market_bars b
               JOIN reference_instruments i ON i.instrument_id=b.instrument_id
               WHERE i.exchange='NSE' AND i.symbol='NIFTY 500'
               AND b.as_of_date >= '2021-01-01' ORDER BY b.as_of_date"""
            )
        ]
        all_sessions = benchmark_sessions or [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT as_of_date FROM market_bars WHERE as_of_date >= '2021-01-01' ORDER BY as_of_date"
            )
        ]
        next_session = next((day for day in all_sessions if day > end_date), None)
        load_end = next_session or end_date
        sessions = [day for day in all_sessions if day <= load_end]
        histories = {instrument: (symbol, []) for instrument, symbol in chosen.values()}
        count = 0
        for row in connection.execute(
            """SELECT instrument_id, as_of_date, open, high, low, close, volume, snapshot_id
               FROM market_bars WHERE as_of_date BETWEEN '2021-01-01' AND ?
               ORDER BY instrument_id, as_of_date""",
            (load_end,),
        ):
            if row["instrument_id"] not in histories:
                continue
            bar = dict(row)
            instrument_id = str(bar.pop("instrument_id"))
            histories[instrument_id][1].append(bar)
            count += 1
        schedule = {}
        for day in sessions:
            selected = next(
                (row for row in reversed(relevant) if row["snapshot_date"] <= day), relevant[0]
            )
            schedule[day] = {
                "snapshot_id": selected["snapshot_id"],
                "symbols": sorted(
                    chosen[isin][1] for isin in members[selected["snapshot_id"]] if isin in chosen
                ),
                "earliest_fallback": day < relevant[0]["snapshot_date"],
            }
        membership_hash = hashlib.sha256(
            json.dumps(
                {
                    "snapshots": relevant,
                    "members": {key: sorted(value) for key, value in members.items()},
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        coverage = {
            "universe_source": "nifty500_snapshot",
            "universe_snapshot_id": relevant[-1]["snapshot_id"],
            "snapshot_date": relevant[-1]["snapshot_date"],
            "universe_sha256": membership_hash,
            "membership_sha256": membership_hash,
            "membership_by_day": schedule,
            "included_member_count": len(isins),
            "matched_isin_count": len(chosen),
            "instruments_with_bars": sum(bool(bars) for _, bars in histories.values()),
            "bar_count": count,
            "session_count": len(sessions),
            "first_session": min(sessions) if sessions else None,
            "last_session": max(sessions) if sessions else None,
            "missing_isins": sorted(isins - chosen.keys()),
            "historical_membership": "as_of_snapshot_with_earliest_fallback",
            "exit_only_session": next_session,
            "corporate_action_adjustment": "stored_provider_history",
        }
        return histories, sessions, coverage
    finally:
        connection.close()


def benchmark_price_return(database: Path, first_session: str, last_session: str) -> dict | None:
    """NIFTY 500 price-index comparison; dividends are not included."""
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT instrument_id FROM reference_instruments "
            "WHERE exchange='NSE' AND symbol='NIFTY 500' ORDER BY observed_on DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        bars = connection.execute(
            "SELECT as_of_date, close FROM market_bars WHERE instrument_id=? "
            "AND as_of_date BETWEEN ? AND ? ORDER BY as_of_date",
            (row[0], first_session, last_session),
        ).fetchall()
        if len(bars) < 2:
            return None
        first, last = bars[0], bars[-1]
        total = float(last[1]) / float(first[1]) - 1
        elapsed = (date.fromisoformat(last[0]) - date.fromisoformat(first[0])).days
        return {
            "name": "NIFTY 500 price index",
            "first_date": first[0],
            "last_date": last[0],
            "first_close": float(first[1]),
            "last_close": float(last[1]),
            "total_return": total,
            "cagr": (1 + total) ** (365.25 / elapsed) - 1 if elapsed > 0 else None,
            "dividends_included": False,
        }
    finally:
        connection.close()
