from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from src.domains.market_data import NormalizedBar
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.positional_trend_backtest_inputs import load_data


def test_snapshot_replay_loads_historical_non_eq_members_and_earliest_fallback(tmp_path):
    from src.gates.workflows.positional_trend_backtest_inputs import load_snapshot_universe

    db = tmp_path / "system.db"
    market = MarketRepository(db)
    market.upsert_instruments(
        [
            TrackedInstrument(name, name.upper(), name.upper(), "NSE", str(index), date(2026, 1, 1))
            for index, name in enumerate(["old", "new"], 1)
        ]
    )
    for snapshot, day, isin, series in [
        ("first", date(2026, 6, 5), "OLD", "BE"),
        ("second", date(2026, 6, 8), "NEW", "BZ"),
    ]:
        market.create_universe_snapshot(
            snapshot_id=snapshot,
            index_name="NIFTY 500",
            snapshot_date=day,
            source_url="fixture://membership",
            raw_csv=snapshot.encode(),
            members=[
                {
                    "isin": isin,
                    "symbol": isin,
                    "company_name": isin,
                    "industry": "IT",
                    "series": series,
                }
            ],
        )
    for name in ["old", "new"]:
        market.upsert_bars(
            name,
            [
                NormalizedBar(
                    name, day, Decimal(100), Decimal(100), Decimal(100), Decimal(100), 100
                )
                for day in [date(2026, 6, 4), date(2026, 6, 5), date(2026, 6, 8), date(2026, 6, 9)]
            ],
            "source",
        )
    histories, sessions, coverage = load_snapshot_universe(db, end_date="2026-06-08")
    assert set(histories) == {"old", "new"}
    assert coverage["membership_by_day"]["2026-06-04"]["symbols"] == ["OLD"]
    assert coverage["membership_by_day"]["2026-06-04"]["earliest_fallback"] is True
    assert coverage["membership_by_day"]["2026-06-08"]["symbols"] == ["NEW"]
    assert coverage["exit_only_session"] == "2026-06-09"
    assert sessions[-1] == "2026-06-09"


def test_market_cap_loader_includes_both_exchanges_and_excludes_below_threshold(tmp_path):
    from src.gates.workflows.positional_trend_backtest_inputs import load_market_cap_universe

    database = tmp_path / "market.db"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE reference_instruments(instrument_id TEXT, symbol TEXT, exchange TEXT, observed_on TEXT);
        CREATE TABLE universe_membership(instrument_id TEXT, isin TEXT, exchange TEXT,
                                         last_market_cap REAL, snapshot_date TEXT);
        CREATE TABLE market_bars(instrument_id TEXT, as_of_date TEXT, open REAL, high REAL,
                                 low REAL, close REAL, volume REAL);
        INSERT INTO reference_instruments VALUES ('a','A','NSE','2026-09-19'),
            ('b','B','BSE','2026-09-19'), ('c','C','NSE','2026-09-19'),
            ('index','NIFTY 500','NSE','2026-09-19');
        INSERT INTO universe_membership VALUES ('a','isin-a','NSE',6000000000,'2026-09-19'),
            ('b','isin-b','BSE',5000000000,'2026-09-19'),
            ('c','isin-c','NSE',4999999999,'2026-09-19');
        INSERT INTO market_bars VALUES ('a','2022-01-03',100,101,99,100,1000000),
            ('b','2022-01-03',100,101,99,100,1000000),
            ('index','2022-01-03',100,101,99,100,0);
    """)
    connection.commit()
    connection.close()
    histories, sessions, coverage = load_market_cap_universe(database, end_date="2026-09-28")
    assert set(histories) == {"a", "b"}
    assert sessions == ["2022-01-03"]
    assert coverage["members_by_exchange"] == {"NSE": 1, "BSE": 1}
    assert coverage["membership_snapshot_dates"] == ["2026-09-19"]


def test_constituent_loader_includes_be_only_when_requested(tmp_path):
    database = tmp_path / "bars.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE reference_instruments (instrument_id, isin, symbol, observed_on, exchange);"
            "CREATE TABLE market_bars (instrument_id, as_of_date, open, high, low, close, volume);"
            "INSERT INTO reference_instruments VALUES ('a','ISINA','A','2026-01-01','NSE'),"
            "('b','ISINB','B','2026-01-01','BSE');"
            "INSERT INTO market_bars VALUES ('a','2022-01-03',100,101,99,100,1000),"
            "('b','2022-01-03',100,101,99,100,1000);"
        )
    constituents = tmp_path / "members.csv"
    constituents.write_text("Symbol,Series,ISIN Code\nA,EQ,ISINA\nB,BE,ISINB\n", encoding="utf-8")
    eq, _, eq_coverage = load_data(database, constituents, end_date="2022-01-03")
    both, _, coverage = load_data(database, constituents, end_date="2022-01-03", include_be=True)
    assert set(eq) == {"a"}
    assert set(both) == {"a", "b"}
    assert eq_coverage["included_series"] == ["EQ"]
    assert coverage["constituent_eq_count"] == 1
    assert coverage["included_member_count"] == 2
    assert coverage["bar_count"] == 2
    assert coverage["matched_members_by_exchange"] == {"NSE": 1, "BSE": 1}
