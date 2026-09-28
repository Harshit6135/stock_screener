"""Read-only audit of benchmark discontinuities against Strategy 3 artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
import zlib
from collections import Counter
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

DEFAULT_INDICATOR_CATEGORY = "research/strategy3-indicators"
DEFAULT_EVENT_CATEGORY = "research/strategy3-event-study"


def benchmark_discontinuities(
    rows: list[tuple[str, object]],
    *,
    up_threshold: float = 0.80,
    down_threshold: float = -0.45,
    max_gap_days: int = 4,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Audit returns between consecutive valid benchmark observations.

    Calendar gaps longer than ``max_gap_days`` are sparse source intervals, not
    one-session returns, and are reported separately instead of being tested.
    """
    valid: list[tuple[date, float]] = []
    invalid: list[dict[str, Any]] = []
    for raw_day, raw_close in rows:
        try:
            day = date.fromisoformat(str(raw_day))
            close = float(raw_close)
            if not math.isfinite(close) or close <= 0:
                raise ValueError("close must be finite and positive")
        except (TypeError, ValueError) as exc:
            invalid.append({"date": str(raw_day), "close": raw_close, "reason": str(exc)})
            continue
        valid.append((day, close))
    valid.sort(key=lambda item: item[0])

    duplicates = [day.isoformat() for day, count in Counter(day for day, _ in valid).items() if count > 1]
    deduplicated: list[tuple[date, float]] = []
    for item in valid:
        if deduplicated and item[0] == deduplicated[-1][0]:
            continue
        deduplicated.append(item)

    flagged: list[dict[str, Any]] = []
    sparse: list[dict[str, Any]] = []
    tested_pairs = 0
    for (previous_day, previous_close), (day, close) in pairwise(deduplicated):
        gap_days = (day - previous_day).days
        if gap_days > max_gap_days:
            sparse.append({
                "previous_date": previous_day.isoformat(),
                "date": day.isoformat(),
                "calendar_gap_days": gap_days,
            })
            continue
        tested_pairs += 1
        return_value = close / previous_close - 1.0
        if return_value > up_threshold or return_value < down_threshold:
            flagged.append({
                "previous_date": previous_day.isoformat(),
                "date": day.isoformat(),
                "previous_close": previous_close,
                "close": close,
                "return": return_value,
                "close_ratio": close / previous_close,
                "direction": "up" if return_value > up_threshold else "down",
                "calendar_gap_days": gap_days,
            })

    by_year = Counter(item["date"][:4] for item in flagged)
    return {
        "input_rows": len(rows),
        "valid_unique_observations": len(deduplicated),
        "invalid_observation_count": len(invalid),
        "invalid_observation_samples": invalid[:sample_limit],
        "duplicate_date_count": len(duplicates),
        "duplicate_date_samples": duplicates[:sample_limit],
        "candidate_adjacent_pairs": max(0, len(deduplicated) - 1),
        "tested_adjacent_pairs": tested_pairs,
        "sparse_pair_count": len(sparse),
        "sparse_pair_samples": sparse[:sample_limit],
        "flagged_count": len(flagged),
        "flagged_by_year": dict(sorted(by_year.items())),
        "flagged_samples": flagged[:sample_limit],
        "flagged_dates": [item["date"] for item in flagged],
    }


def _connect_read_only(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")
    connection = sqlite3.connect(
        f"file:{database.resolve().as_posix()}?mode=ro&immutable=1", uri=True
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _load_artifact(
    connection: sqlite3.Connection, category: str, artifact_id: str
) -> dict[str, Any]:
    row = connection.execute(
        """SELECT payload_zlib, checksum_sha256 FROM artifact_payloads
           WHERE category=? AND artifact_id=? AND quarantined=0""",
        (category, artifact_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"artifact not found: {category}/{artifact_id}")
    raw = zlib.decompress(row["payload_zlib"])
    if hashlib.sha256(raw).hexdigest() != row["checksum_sha256"]:
        raise ValueError(f"artifact checksum mismatch: {category}/{artifact_id}")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError(f"artifact payload is not an object: {category}/{artifact_id}")
    return payload


def _benchmark_rows(
    connection: sqlite3.Connection, symbol: str, exchange: str
) -> tuple[str, list[tuple[str, object]]]:
    instruments = connection.execute(
        "SELECT instrument_id FROM reference_instruments WHERE symbol=? AND exchange=?",
        (symbol, exchange),
    ).fetchall()
    if len(instruments) != 1:
        raise ValueError(
            f"benchmark identity must resolve exactly once; found {len(instruments)} rows for "
            f"{exchange}:{symbol}"
        )
    instrument_id = str(instruments[0]["instrument_id"])
    rows = connection.execute(
        "SELECT as_of_date, close FROM market_bars WHERE instrument_id=? ORDER BY as_of_date",
        (instrument_id,),
    ).fetchall()
    return instrument_id, [(str(row["as_of_date"]), row["close"]) for row in rows]


def stock_discontinuities(
    connection: sqlite3.Connection,
    benchmark_dates: list[str],
    *,
    exchange: str = "NSE",
    up_threshold: float = 0.80,
    down_threshold: float = -0.45,
    sample_limit: int = 20,
) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    """Audit each NSE stock only across consecutive benchmark sessions."""
    benchmark_index = {day: index for index, day in enumerate(benchmark_dates)}
    instruments = connection.execute(
        """SELECT instrument_id, symbol FROM reference_instruments
           WHERE exchange=? AND isin NOT LIKE 'INDEX:%'
           ORDER BY instrument_id""",
        (exchange,),
    ).fetchall()
    flagged_keys: set[tuple[str, str]] = set()
    flagged_samples: list[dict[str, Any]] = []
    nonadjacent_samples: list[dict[str, Any]] = []
    invalid_samples: list[dict[str, Any]] = []
    by_year: Counter[str] = Counter()
    by_instrument: Counter[str] = Counter()
    instruments_without_bars = 0
    observation_count = 0
    tested_pairs = 0
    nonadjacent_pairs = 0
    invalid_observations = 0

    for instrument in instruments:
        instrument_id = str(instrument["instrument_id"])
        symbol = str(instrument["symbol"])
        rows = connection.execute(
            """SELECT as_of_date, close FROM market_bars
               WHERE instrument_id=? ORDER BY as_of_date""",
            (instrument_id,),
        )
        previous: tuple[str, float] | None = None
        instrument_observations = 0
        for row in rows:
            raw_day, raw_close = str(row["as_of_date"]), row["close"]
            observation_count += 1
            instrument_observations += 1
            try:
                date.fromisoformat(raw_day)
                close = float(raw_close)
                if not math.isfinite(close) or close <= 0:
                    raise ValueError("close must be finite and positive")
            except (TypeError, ValueError) as exc:
                invalid_observations += 1
                if len(invalid_samples) < sample_limit:
                    invalid_samples.append({
                        "instrument_id": instrument_id,
                        "symbol": symbol,
                        "date": raw_day,
                        "close": raw_close,
                        "reason": str(exc),
                    })
                previous = None
                continue
            if previous is not None:
                previous_day, previous_close = previous
                previous_index = benchmark_index.get(previous_day)
                current_index = benchmark_index.get(raw_day)
                if (
                    previous_index is None
                    or current_index is None
                    or current_index != previous_index + 1
                ):
                    nonadjacent_pairs += 1
                    if len(nonadjacent_samples) < sample_limit:
                        nonadjacent_samples.append({
                            "instrument_id": instrument_id,
                            "symbol": symbol,
                            "previous_date": previous_day,
                            "date": raw_day,
                            "reason": "dates are not consecutive benchmark sessions",
                        })
                else:
                    tested_pairs += 1
                    return_value = close / previous_close - 1.0
                    if return_value > up_threshold or return_value < down_threshold:
                        flagged_keys.add((instrument_id, raw_day))
                        by_year[raw_day[:4]] += 1
                        by_instrument[instrument_id] += 1
                        if len(flagged_samples) < sample_limit:
                            flagged_samples.append({
                                "instrument_id": instrument_id,
                                "symbol": symbol,
                                "previous_date": previous_day,
                                "date": raw_day,
                                "previous_close": previous_close,
                                "close": close,
                                "return": return_value,
                                "close_ratio": close / previous_close,
                                "direction": "up" if return_value > up_threshold else "down",
                            })
            previous = (raw_day, close)
        if instrument_observations == 0:
            instruments_without_bars += 1

    report = {
        "instrument_count": len(instruments),
        "instruments_without_bars": instruments_without_bars,
        "observation_count": observation_count,
        "tested_adjacent_pairs": tested_pairs,
        "nonadjacent_pair_count": nonadjacent_pairs,
        "nonadjacent_pair_samples": nonadjacent_samples,
        "invalid_observation_count": invalid_observations,
        "invalid_observation_samples": invalid_samples,
        "flagged_count": len(flagged_keys),
        "flagged_by_year": dict(sorted(by_year.items())),
        "flagged_by_instrument": dict(sorted(by_instrument.items())),
        "flagged_samples": flagged_samples,
        "flag_key_format": ["instrument_id", "date"],
    }
    return report, flagged_keys


def artifact_intersection_audit(
    indicator: dict[str, Any],
    event: dict[str, Any],
    benchmark_dates: list[str],
    benchmark_flagged_dates: set[str],
    stock_flagged_keys: set[tuple[str, str]],
    *,
    lookback_sessions: int = 316,
    sample_limit: int = 20,
) -> dict[str, Any]:
    indicator_rows = indicator.get("rows")
    events = event.get("events")
    if not isinstance(indicator_rows, dict):
        raise TypeError("indicator artifact has no object-valued rows")
    if not isinstance(events, list):
        raise TypeError("event artifact has no list-valued events")

    benchmark_index = {day: index for index, day in enumerate(benchmark_dates)}
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    benchmark_contaminated_lookbacks: list[dict[str, Any]] = []
    stock_contaminated_lookbacks: list[dict[str, Any]] = []
    insufficient_lookbacks: list[dict[str, Any]] = []
    benchmark_outcome_crossings: list[dict[str, Any]] = []
    stock_outcome_crossings: list[dict[str, Any]] = []
    outcome_anchor_missing: list[dict[str, Any]] = []
    completed_horizons = Counter()
    benchmark_crossing_horizons = Counter()
    stock_crossing_horizons = Counter()

    for position, selected in enumerate(events):
        if not isinstance(selected, dict):
            unmatched.append({"event_index": position, "reason": "event is not an object"})
            continue
        instrument_id = str(selected.get("instrument_id", ""))
        signal_day = str(selected.get("signal_date", ""))
        series = indicator_rows.get(instrument_id)
        if not isinstance(series, dict) or signal_day not in series:
            unmatched.append({
                "event_index": position,
                "instrument_id": instrument_id,
                "signal_date": signal_day,
                "reason": "signal absent from indicator artifact",
            })
            continue
        matched.append(selected)
        signal_index = benchmark_index.get(signal_day)
        if signal_index is None or signal_index < lookback_sessions:
            insufficient_lookbacks.append({
                "event_index": position,
                "instrument_id": instrument_id,
                "signal_date": signal_day,
                "available_prior_benchmark_sessions": signal_index,
                "reason": "signal missing from benchmark" if signal_index is None else "insufficient history",
            })
        else:
            prior_dates = benchmark_dates[signal_index - lookback_sessions : signal_index]
            benchmark_hits = sorted(benchmark_flagged_dates.intersection(prior_dates))
            stock_hits = [day for day in prior_dates if (instrument_id, day) in stock_flagged_keys]
            if benchmark_hits:
                benchmark_contaminated_lookbacks.append({
                    "event_index": position,
                    "instrument_id": instrument_id,
                    "signal_date": signal_day,
                    "flagged_dates": benchmark_hits,
                })
            if stock_hits:
                stock_contaminated_lookbacks.append({
                    "event_index": position,
                    "instrument_id": instrument_id,
                    "signal_date": signal_day,
                    "flagged_dates": stock_hits,
                })

        next_session = selected.get("next_session")
        outcome_start = benchmark_index.get(str(next_session)) if next_session is not None else None
        event_benchmark_crossings: dict[str, list[str]] = {}
        event_stock_crossings: dict[str, list[str]] = {}
        has_completed_outcome = False
        for horizon in (1, 2, 5, 10, 20):
            if selected.get(f"h{horizon}_status") != "complete":
                continue
            has_completed_outcome = True
            completed_horizons[str(horizon)] += 1
            if outcome_start is None:
                continue
            outcome_dates = benchmark_dates[outcome_start : outcome_start + horizon]
            benchmark_hits = sorted(benchmark_flagged_dates.intersection(outcome_dates))
            stock_hits = [
                day for day in outcome_dates if (instrument_id, day) in stock_flagged_keys
            ]
            if benchmark_hits:
                event_benchmark_crossings[str(horizon)] = benchmark_hits
                benchmark_crossing_horizons[str(horizon)] += 1
            if stock_hits:
                event_stock_crossings[str(horizon)] = stock_hits
                stock_crossing_horizons[str(horizon)] += 1
        if has_completed_outcome and outcome_start is None:
            outcome_anchor_missing.append({
                "event_index": position,
                "instrument_id": instrument_id,
                "signal_date": signal_day,
                "next_session": next_session,
            })
        if event_benchmark_crossings:
            benchmark_outcome_crossings.append({
                "event_index": position,
                "instrument_id": instrument_id,
                "signal_date": signal_day,
                "crossing_horizons": event_benchmark_crossings,
            })
        if event_stock_crossings:
            stock_outcome_crossings.append({
                "event_index": position,
                "instrument_id": instrument_id,
                "signal_date": signal_day,
                "crossing_horizons": event_stock_crossings,
            })

    return {
        "selected_signal_count": len(events),
        "indicator_intersection_count": len(matched),
        "indicator_nonintersection_count": len(unmatched),
        "indicator_nonintersection_samples": unmatched[:sample_limit],
        "lookback_sessions": lookback_sessions,
        "lookback_assessed_count": len(matched) - len(insufficient_lookbacks),
        "lookback_insufficient_count": len(insufficient_lookbacks),
        "lookback_insufficient_samples": insufficient_lookbacks[:sample_limit],
        "signals_with_benchmark_flagged_lookback_count": len(benchmark_contaminated_lookbacks),
        "signals_with_benchmark_flagged_lookback_samples": benchmark_contaminated_lookbacks[:sample_limit],
        "signals_with_same_stock_flagged_lookback_count": len(stock_contaminated_lookbacks),
        "signals_with_same_stock_flagged_lookback_samples": stock_contaminated_lookbacks[:sample_limit],
        "completed_outcomes_by_horizon": dict(completed_horizons),
        "completed_outcomes_crossing_benchmark_flags_by_horizon": dict(benchmark_crossing_horizons),
        "completed_outcomes_crossing_same_stock_flags_by_horizon": dict(stock_crossing_horizons),
        "events_with_completed_outcome_crossing_benchmark_flag_count": len(benchmark_outcome_crossings),
        "events_with_completed_outcome_crossing_benchmark_flag_samples": benchmark_outcome_crossings[:sample_limit],
        "events_with_completed_outcome_crossing_same_stock_flag_count": len(stock_outcome_crossings),
        "events_with_completed_outcome_crossing_same_stock_flag_samples": stock_outcome_crossings[:sample_limit],
        "completed_outcome_missing_benchmark_anchor_count": len(outcome_anchor_missing),
        "completed_outcome_missing_benchmark_anchor_samples": outcome_anchor_missing[:sample_limit],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("instance/system.db"))
    parser.add_argument("--indicator-artifact-id", required=True)
    parser.add_argument("--event-artifact-id", required=True)
    parser.add_argument("--indicator-category", default=DEFAULT_INDICATOR_CATEGORY)
    parser.add_argument("--event-category", default=DEFAULT_EVENT_CATEGORY)
    parser.add_argument("--benchmark-symbol", default="NIFTY 50")
    parser.add_argument("--benchmark-exchange", default="NSE")
    parser.add_argument("--up-threshold", type=float, default=0.80)
    parser.add_argument("--down-threshold", type=float, default=-0.45)
    parser.add_argument("--max-gap-days", type=int, default=4)
    parser.add_argument("--lookback-sessions", type=int, default=316)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not 0 < args.up_threshold or not -1 < args.down_threshold < 0:
            raise ValueError("thresholds must satisfy up > 0 and -1 < down < 0")
        if args.max_gap_days < 1 or args.lookback_sessions < 1 or args.sample_limit < 0:
            raise ValueError("gap, lookback, and sample arguments are out of range")
        with _connect_read_only(args.database) as connection:
            benchmark_id, rows = _benchmark_rows(
                connection, args.benchmark_symbol, args.benchmark_exchange
            )
            discontinuities = benchmark_discontinuities(
                rows,
                up_threshold=args.up_threshold,
                down_threshold=args.down_threshold,
                max_gap_days=args.max_gap_days,
                sample_limit=args.sample_limit,
            )
            indicator = _load_artifact(
                connection, args.indicator_category, args.indicator_artifact_id
            )
            event = _load_artifact(connection, args.event_category, args.event_artifact_id)
            valid_dates = sorted({
                str(day)
                for day, close in rows
                if _valid_benchmark_observation(day, close)
            })
            stock_report, stock_flagged_keys = stock_discontinuities(
                connection,
                valid_dates,
                exchange=args.benchmark_exchange,
                up_threshold=args.up_threshold,
                down_threshold=args.down_threshold,
                sample_limit=args.sample_limit,
            )
        report = {
            "status": "ok",
            "read_only": True,
            "database": str(args.database.resolve()),
            "benchmark": {
                "instrument_id": benchmark_id,
                "symbol": args.benchmark_symbol,
                "exchange": args.benchmark_exchange,
            },
            "criteria": {
                "up_return_strictly_greater_than": args.up_threshold,
                "down_return_strictly_less_than": args.down_threshold,
                "equivalent_close_ratio_strictly_greater_than": 1 + args.up_threshold,
                "equivalent_close_ratio_strictly_less_than": 1 + args.down_threshold,
                "maximum_calendar_gap_days": args.max_gap_days,
            },
            "discontinuities": discontinuities,
            "stock_discontinuities": stock_report,
            "artifact_audit": artifact_intersection_audit(
                indicator,
                event,
                valid_dates,
                set(discontinuities["flagged_dates"]),
                stock_flagged_keys,
                lookback_sessions=args.lookback_sessions,
                sample_limit=args.sample_limit,
            ),
            "artifact_ids": {
                "indicator": args.indicator_artifact_id,
                "event": args.event_artifact_id,
            },
            "interpretation": (
                "Extreme returns are audit flags, not proof of genuine market moves; they may indicate "
                "instrument identity, token history, adjustment, or source-data errors."
            ),
        }
        encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is not None:
            args.output.write_text(encoded, encoding="utf-8")
        sys.stdout.write(encoded)
        return 0
    except (OSError, sqlite3.Error, TypeError, ValueError, zlib.error) as exc:
        error = {"status": "error", "read_only": True, "error": str(exc)}
        sys.stdout.write(json.dumps(error, indent=2, sort_keys=True) + "\n")
        return 2


def _valid_benchmark_observation(raw_day: object, raw_close: object) -> bool:
    try:
        date.fromisoformat(str(raw_day))
        close = float(raw_close)
        return math.isfinite(close) and close > 0
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
