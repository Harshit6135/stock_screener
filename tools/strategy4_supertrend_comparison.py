"""Read-only portfolio comparison of v4 and installed pandas-ta Supertrend."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import sys
from collections import Counter
from datetime import datetime
from importlib import import_module, metadata
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application import positional_trend_backtest as replay
from src.application.positional_trend import _segment_features, feature_series, valid_bar


def pandas_ta_features(bars: list[dict], sessions: list[str], symbol: str,
                       rules: dict | None = None) -> list[dict]:
    """Change only Supertrend and its dependent entry, anchor and exit decisions."""
    rules = rules or {}
    by_date = {str(bar["as_of_date"]): bar for bar in bars}
    segments, segment = [], []
    for day in sessions:
        bar = by_date.get(day)
        if bar is None:
            continue
        if not valid_bar(bar):
            if segment:
                segments.append(segment)
                segment = []
        else:
            segment.append(bar)
    if segment:
        segments.append(segment)
    result = []
    supertrend = import_module("pandas_ta.overlap.supertrend").supertrend
    for segment in segments:
        rows = _segment_features(segment, symbol, rules)
        if not rows:
            continue
        frame = pd.DataFrame(segment).set_index("as_of_date")
        values = supertrend(frame["high"].astype(float), frame["low"].astype(float),
                            frame["close"].astype(float),
                            length=int(rules.get("atr_period", 10)),
                            atr_length=int(rules.get("atr_period", 10)),
                            multiplier=float(rules.get("supertrend_multiplier", 3)),
                            atr_mamode="rma")
        if values is None:
            raise ValueError(f"pandas-ta Supertrend produced no values for {symbol}")
        line_column = next(column for column in values if column.startswith("SUPERT_"))
        direction_column = next(column for column in values if column.startswith("SUPERTd_"))
        lines = values[line_column].to_dict()
        directions = values[direction_column].to_dict()
        for row in rows:
            line = float(lines[row["signal_date"]])
            if not math.isfinite(line):
                raise ValueError(f"pandas-ta Supertrend is not warmed for {symbol} at {row['signal_date']}")
            bullish = bool(directions[row["signal_date"]] > 0)
            row.update({"supertrend": line, "supertrend_bullish": bullish,
                        "initial_stop_anchor": max(line, row["lower20"]),
                        "filtered": bool(row["first_cross"] and row["adx14"] is not None
                                         and row["adx14"] > float(rules.get("adx_minimum", 25))
                                         and bullish and row["close"] > line),
                        "exit_signal": bool(row["close"] < line or row["close"] < row["lower20"])})
        result.extend(rows)
    return result


def compare(database: Path, universe_csv: Path, *, include_be: bool,
            start: str, end: str, output: Path) -> dict:
    definition = yaml.safe_load((ROOT / "strategies/strategy4.yml").read_text())
    rules = {**definition["signal_rules"], "required_sessions": definition["calculation"]["required_sessions"]}
    settings = definition["portfolio_policy"]
    policy = replay.Policy(float(settings["initial_capital"]), int(settings["max_positions"]),
                           float(settings["max_order_fraction"]), float(settings["risk_fraction"]),
                           float(settings["adv_participation_fraction"]), float(settings["round_trip_cost_bps"]), False)
    began = perf_counter()
    histories, sessions, coverage = replay.load_data(database, universe_csv, end_date=end, include_be=include_be)
    load_seconds = perf_counter() - began
    source_hash = hashlib.sha256(json.dumps(histories, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    module = import_module("pandas_ta.overlap.supertrend")
    runs = {}
    for name, calculate in (("v4_current_bands", feature_series), ("pandas_ta_previous_bands", pandas_ta_features)):
        counts = Counter()
        feature_seconds = 0.0
        def provider(bars, calendar, symbol, active_rules, calculate=calculate, counts=counts, name=name):
            nonlocal feature_seconds
            at = perf_counter()
            rows = calculate(bars, calendar, symbol, active_rules)
            feature_seconds += perf_counter() - at
            counts["instruments"] += 1
            eligible = [row for row in rows if start <= row["signal_date"] <= end]
            counts["first_cross"] += sum(row["first_cross"] for row in eligible)
            counts["filtered_entries"] += sum(row["filtered"] for row in eligible)
            if counts["instruments"] % 100 == 0:
                print(f"{universe_csv.stem} {name}: {counts['instruments']}/{len(histories)} instruments", flush=True)
            return rows
        began = perf_counter()
        with patch.object(replay, "feature_series", provider):
            result = replay.simulate(histories, sessions, policy=policy, start_date=start, end_date=end, rules=rules)
        result.update({"variant": name, "data": coverage, "signal_counts": dict(counts),
                       "timing": {"feature_seconds": feature_seconds, "replay_seconds": perf_counter() - began}})
        runs[name] = result
        print(json.dumps({"universe": universe_csv.name, "variant": name,
                          "performance": result["performance"], "timing": result["timing"]}), flush=True)
    report = {"requested_period": {"start": start, "end": end}, "database": str(database.resolve()),
              "data": coverage, "source_ohlcv_sha256": source_hash, "load_seconds": load_seconds,
              "rules": rules, "package": {"pandas_ta_version": metadata.version("pandas-ta"),
                                           "talib_available_to_pandas_ta": import_module("pandas_ta").Imports["talib"],
                                           "supertrend_source_sha256": hashlib.sha256(inspect.getsource(module.supertrend).encode()).hexdigest()},
              "benchmark": replay.benchmark_price_return(database, runs["v4_current_bands"]["period"]["first_session"],
                                                          runs["v4_current_bands"]["period"]["last_session"]),
              "limitations": ["current constituent membership applied retrospectively",
                              "corporate actions ignored per user scope",
                              "daily OHLCV cannot establish upper-circuit or opening fill availability",
                              "open holdings valued at latest stored close; not forcibly sold",
                              "pandas-ta Supertrend also uses its native ATR initialization; other indicators are unchanged",
                              "timing compares complete feature paths, not isolated library kernels",
                              "exploratory simulation; not a blind holdout or a Phase 1 advancement result"],
              "runs": runs}
    output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "instance/system.db")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default=datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat())
    parser.add_argument("--output-dir", type=Path, default=ROOT / "backtesting_results")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, csv_file, include_be in (("nifty500", "ind_nifty500list.csv", False),
                                       ("totalmarket", "ind_niftytotalmarket_list.csv", True)):
        output = args.output_dir / f"strategy4_supertrend_{name}_{args.end.replace('-', '')}.json"
        compare(args.database, ROOT / csv_file, include_be=include_be, start=args.start, end=args.end, output=output)
        print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
