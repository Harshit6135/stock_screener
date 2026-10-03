"""Read-only positional trend event study and historical-input validation.

Usage:
    python tools/positional_trend_event_study.py \
        --output backtesting_results/positional_trend_event_study.json
The current Nifty 500 CSV is applied to past dates (survivorship bias).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domains.backtesting.event_study import (
    WINDOWS,
    evaluate_signal,
    validation_gate,
    window_report,
)
from src.domains.strategies.positional_trend import signal_series
from src.gates.workflows.positional_trend_backtest_inputs import load_data


def run(database: Path, universe_csv: Path, *, seed: int = 4, replicates: int = 5000) -> dict:
    histories, sessions, coverage = load_data(database, universe_csv)
    day_index = {day: i for i, day in enumerate(sessions)}
    events = []
    for symbol, bars in histories.values():
        by_day = {str(bar["as_of_date"]): bar for bar in bars}
        for signal in signal_series(bars, sessions, symbol):
            if "2022-01-01" <= signal["signal_date"] <= "2025-12-31":
                events.append(evaluate_signal(signal, by_day, sessions, day_index))
    events.sort(key=lambda e: (e["signal_date"], e["symbol"]))
    windows = {}
    for offset, (label, (start, end)) in enumerate(WINDOWS.items()):
        cohort = [e for e in events if start <= e["signal_date"] <= end]
        calendar = [day for day in sessions if start <= day <= end]
        windows[label] = window_report(cohort, calendar, seed=seed + offset * 1000,
                                       replicates=replicates)
    return {"strategy": "positional_trend_following", "data": coverage,
            "assumptions": {"round_trip_cost_bps": 50, "fill": "next_exchange_open_if_OHLCV_bar_exists",
                            "upper_price_circuit": "not_observable_in_daily_OHLCV",
                            "portfolio_constraints": "not_applied_in_phase1",
                            "entry_stop_filter": "not_applied_in_phase1"},
            "windows": windows,
            "phase1_gate": validation_gate(windows["development"], windows["validation_previously_viewed"]),
            "events": events}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "instance/system.db")
    parser.add_argument("--universe-csv", type=Path, default=ROOT / "ind_nifty500list.csv")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=4)
    parser.add_argument("--bootstrap-replicates", type=int, default=5000)
    args = parser.parse_args(argv)
    if args.bootstrap_replicates < 100:
        parser.error("at least 100 bootstrap replicates are required")
    result = run(args.database, args.universe_csv, seed=args.seed,
                 replicates=args.bootstrap_replicates)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({"output": str(args.output), "phase1_gate": result["phase1_gate"],
                      "raw_signals": {name: item["raw_baseline_signals"]
                                      for name, item in result["windows"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
