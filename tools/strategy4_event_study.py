"""Read-only Strategy 4 event study and previously-viewed validation.

Usage: python tools/strategy4_event_study.py --output backtesting_results/strategy4_event_study.json
The current Nifty 500 CSV is applied to past dates (survivorship bias).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.positional_trend import signal_series, valid_bar
from src.application.positional_trend_backtest import load_data

WINDOWS = {
    "development": ("2022-01-01", "2023-12-31"),
    "validation_previously_viewed": ("2024-01-01", "2025-12-31"),
}
HORIZONS = (5, 20, 50)
COST = 0.005


def evaluate_signal(signal: dict, by_day: dict[str, dict], sessions: list[str], day_index: dict) -> dict:
    event = {**signal, "status": "missing_next_open"}
    at = day_index[signal["signal_date"]]
    if at + 1 >= len(sessions):
        return event
    future = sessions[at + 1:at + 51]
    entry = by_day.get(future[0])
    if entry is None or not valid_bar(entry):
        return event
    try:
        fill = float(entry["open"])
    except (TypeError, ValueError):
        return event
    if not math.isfinite(fill) or fill <= 0:
        return event
    event["entry_date"] = future[0]
    event["entry_open"] = fill
    event["gap_pct"] = fill / signal["close"] - 1
    if fill > signal["close"] * 1.03:
        event["status"] = "gap_skipped"
        return event
    # The OHLCV store has no exchange circuit-band or order-book fill field.
    event["status"] = "modeled_fill"
    for horizon in HORIZONS:
        if len(future) < horizon:
            continue
        window = [by_day.get(day) for day in future[:horizon]]
        if any(bar is None or not valid_bar(bar) for bar in window):
            continue
        try:
            lows = [float(bar["low"]) for bar in window]
            highs = [float(bar["high"]) for bar in window]
            final_close = float(window[-1]["close"])
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(x) and x > 0 for x in (*lows, *highs, final_close)):
            continue
        event[f"net_{horizon}"] = final_close / fill - 1 - COST
        event[f"mae_{horizon}"] = max(0.0, 1 - min(lows) / fill)
        event[f"mfe_{horizon}"] = max(0.0, max(highs) / fill - 1)
    return event


def _summary(events: list[dict], horizon: int, *, filtered: bool) -> dict:
    sample = [e for e in events if f"net_{horizon}" in e and (e["filtered"] or not filtered)]
    returns = [e[f"net_{horizon}"] for e in sample]
    mae = sorted(e[f"mae_{horizon}"] for e in sample)
    mfe = [e[f"mfe_{horizon}"] for e in sample]
    return {"complete_events": len(sample),
            "unique_signal_sessions": len({e["signal_date"] for e in sample}),
            "mean_net_return": mean(returns) if returns else None,
            "p90_mae": mae[math.ceil(len(mae) * .9) - 1] if mae else None,
            "mean_mfe": mean(mfe) if mfe else None}


def stationary_interval(events: list[dict], sessions: list[str], horizon: int,
                        *, seed: int, replicates: int = 5000) -> dict:
    """Resample calendar sessions; nested arms and same-day events travel together."""
    if horizon < 1 or replicates < 1:
        raise ValueError("bootstrap horizon and replicate count must be positive")
    per_day = defaultdict(lambda: [0.0, 0, 0.0, 0])
    for event in events:
        key = f"net_{horizon}"
        if key not in event:
            continue
        entry = per_day[event["signal_date"]]
        entry[0] += event[key]
        entry[1] += 1
        if event["filtered"]:
            entry[2] += event[key]
            entry[3] += 1
    if not sessions:
        return {"valid_replicates": 0, "ci95": None, "replicates": replicates,
                "mean_block_sessions": horizon, "random_seed": seed,
                "method": "stationary_calendar_session_block_bootstrap",
                "approx_nonoverlap_blocks": 0}
    arr = np.array([per_day[day] for day in sessions], dtype=float)
    rng = np.random.default_rng(seed)
    indices = rng.integers(len(sessions), size=replicates)
    totals = np.zeros((replicates, 4), dtype=float)
    for _ in sessions:
        totals += arr[indices]
        restart = rng.random(replicates) < 1 / horizon
        indices = np.where(restart, rng.integers(len(sessions), size=replicates),
                           (indices + 1) % len(sessions))
    valid = (totals[:, 1] > 0) & (totals[:, 3] > 0)
    delta = totals[valid, 2] / totals[valid, 3] - totals[valid, 0] / totals[valid, 1]
    return {"method": "stationary_calendar_session_block_bootstrap",
            "mean_block_sessions": horizon, "replicates": replicates,
            "valid_replicates": int(valid.sum()), "random_seed": seed,
            "ci95": [float(x) for x in np.quantile(delta, [.025, .975])] if len(delta) else None,
            "approx_nonoverlap_blocks": len(sessions) / horizon}


def window_report(events: list[dict], sessions: list[str], *, seed: int,
                  replicates: int = 5000) -> dict:
    reports = {}
    for horizon in HORIZONS:
        baseline = _summary(events, horizon, filtered=False)
        strategy = _summary(events, horizon, filtered=True)
        reports[str(horizon)] = {
            "baseline": baseline, "strategy": strategy,
            "mean_net_difference": (
                strategy["mean_net_return"] - baseline["mean_net_return"]
                if strategy["mean_net_return"] is not None and baseline["mean_net_return"] is not None
                else None),
            "uncertainty": stationary_interval(events, sessions, horizon, seed=seed + horizon,
                                               replicates=replicates),
        }
    years = sorted({event["signal_date"][:4] for event in events})
    yearly_20 = {}
    for year in years:
        annual = [event for event in events if event["signal_date"].startswith(year)]
        yearly_20[year] = {"baseline": _summary(annual, 20, filtered=False),
                           "strategy": _summary(annual, 20, filtered=True)}
    return {"raw_baseline_signals": len(events),
            "raw_filtered_signals": sum(e["filtered"] for e in events),
            "execution_status_counts": dict(Counter(e["status"] for e in events)),
            "horizons": reports, "yearly_20": yearly_20}


def validation_gate(development: dict, validation: dict) -> dict:
    dev = development["horizons"]["20"]
    val = validation["horizons"]["20"]
    sufficient = all(
        item[arm]["complete_events"] >= 30
        for item in (dev, val) for arm in ("strategy", "baseline")
    )
    support_by_period = {
        period: item["uncertainty"]["valid_replicates"] >= 0.95 * item["uncertainty"]["replicates"]
                and item["uncertainty"]["ci95"] is not None
        for period, item in (("development", dev), ("validation_previously_viewed", val))
    }
    support = all(support_by_period.values())
    if not sufficient or not support:
        status = "inconclusive"
    elif (dev["mean_net_difference"] > 0
          and dev["uncertainty"]["ci95"][0] > 0
          and val["mean_net_difference"] > 0
          and val["strategy"]["p90_mae"] <= val["baseline"]["p90_mae"]):
        status = "advance_to_portfolio_simulation"
    else:
        status = "does_not_meet_phase1_gate"
    return {"status": status, "minimum_complete_events_per_arm_per_period": 30,
            "bootstrap_support_by_period": support_by_period,
            "development_positive_ci": dev["uncertainty"]["ci95"] is not None and dev["uncertainty"]["ci95"][0] > 0,
            "validation_positive_difference": val["mean_net_difference"] is not None and val["mean_net_difference"] > 0,
            "validation_p90_mae_no_worse": val["strategy"]["p90_mae"] is not None and val["baseline"]["p90_mae"] is not None and val["strategy"]["p90_mae"] <= val["baseline"]["p90_mae"]}


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
    return {"strategy": "strategy4_positional_trend_v4", "data": coverage,
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
