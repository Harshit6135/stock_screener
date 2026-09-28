"""Exercise the audit CLI against a small, read-only source database."""

import hashlib
import json
import sqlite3
import zlib

import pytest

# Historical Strategy 3 coverage is retained for the retirement audit only.
pytestmark = pytest.mark.skip(reason="Strategy 3 is retired; Task 4.3 remains incomplete until runtime source is removed")

from tools.strategy3_data_audit import main


def test_cli_uses_strategy3_categories_and_matches_stock_flags_by_instrument(tmp_path, capsys):
    database = tmp_path / "audit.db"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE reference_instruments (
                instrument_id TEXT, symbol TEXT, exchange TEXT, isin TEXT
            );
            CREATE TABLE market_bars (
                instrument_id TEXT, as_of_date TEXT, close REAL
            );
            CREATE TABLE artifact_payloads (
                category TEXT, artifact_id TEXT, payload_zlib BLOB,
                checksum_sha256 TEXT, quarantined INTEGER
            );
        """)
        connection.executemany(
            "INSERT INTO reference_instruments VALUES (?,?,?,?)",
            [("index", "NIFTY 50", "NSE", "INDEX:N50"),
             ("a", "A", "NSE", "A"), ("b", "B", "NSE", "B")],
        )
        days = ["2024-01-01", "2024-01-02", "2024-01-03"]
        connection.executemany(
            "INSERT INTO market_bars VALUES (?,?,?)",
            [(instrument, day, close)
             for instrument, closes in (("index", [100, 101, 102]),
                                        ("a", [100, 100, 200]),
                                        ("b", [100, 100, 101]))
             for day, close in zip(days, closes)],
        )
        indicator = {"rows": {key: {days[1]: {}} for key in ("a", "b")}}
        events = {"events": [
            {"instrument_id": key, "signal_date": days[1], "next_session": days[2],
             "h1_status": "complete"} for key in ("a", "b")
        ]}
        for category, artifact_id, payload in (
            ("research/strategy3-indicators", "indicators", indicator),
            ("research/strategy3-event-study", "events", events),
        ):
            raw = json.dumps(payload).encode("utf-8")
            connection.execute(
                "INSERT INTO artifact_payloads VALUES (?,?,?,?,0)",
                (category, artifact_id, zlib.compress(raw), hashlib.sha256(raw).hexdigest()),
            )

    assert main(["--database", str(database), "--indicator-artifact-id", "indicators",
                 "--event-artifact-id", "events", "--lookback-sessions", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stock_discontinuities"]["flagged_count"] == 1
    assert report["stock_discontinuities"]["flagged_samples"][0]["instrument_id"] == "a"
    assert report["artifact_audit"]["indicator_intersection_count"] == 2
    assert report["artifact_audit"]["events_with_completed_outcome_crossing_same_stock_flag_count"] == 1
    assert report["artifact_audit"]["events_with_completed_outcome_crossing_same_stock_flag_samples"][0]["instrument_id"] == "a"
