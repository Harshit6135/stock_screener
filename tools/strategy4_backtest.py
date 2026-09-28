"""Strategy 4 CLI using the application portfolio replay engine."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.positional_trend_backtest import (
    Policy,
    benchmark_price_return,
    load_data,
    load_market_cap_universe,
    simulate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "instance/system.db")
    parser.add_argument("--universe-csv", type=Path, default=ROOT / "ind_nifty500list.csv")
    parser.add_argument("--universe-source", choices=("nifty500", "csv", "mcap500"), default="nifty500")
    parser.add_argument("--include-be", action="store_true", help="include BE rows in a constituent CSV")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--end-date", default=datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat())
    parser.add_argument("--initial-capital", type=float, default=500_000)
    parser.add_argument("--max-positions", type=int, default=15)
    parser.add_argument("--max-name-pct", type=float, default=10)
    parser.add_argument("--risk-pct", type=float, default=1)
    parser.add_argument("--adv-participation-pct", type=float, default=1)
    parser.add_argument("--round-trip-cost-bps", type=float, default=50)
    parser.add_argument("--enable-pyramiding", action="store_true")
    args = parser.parse_args(argv)
    policy = Policy(args.initial_capital, args.max_positions, args.max_name_pct / 100,
                    args.risk_pct / 100, args.adv_participation_pct / 100,
                    args.round_trip_cost_bps, args.enable_pyramiding)
    if args.universe_source == "mcap500":
        histories, sessions, coverage = load_market_cap_universe(args.database, end_date=args.end_date)
    else:
        histories, sessions, coverage = load_data(args.database, args.universe_csv,
                                                  end_date=args.end_date, include_be=args.include_be)
    result = simulate(histories, sessions, policy=policy, start_date=args.start_date,
                      end_date=args.end_date)
    result["data"] = coverage
    result["benchmark"] = benchmark_price_return(args.database, result["period"]["first_session"],
                                                  result["period"]["last_session"])
    result["limitations"] = [
        ("current market-cap universe applied retrospectively (survivorship and market-cap look-ahead bias)"
         if args.universe_source == "mcap500" else
         "current constituent CSV membership applied retrospectively (survivorship bias)"),
        "stored OHLCV is used without corporate-action adjustment per research scope",
        "daily OHLCV cannot prove upper-circuit or market-on-open fill availability",
        "missing held-stock bars retain the last observed close for valuation",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({"output": str(args.output), "period": result["period"],
                      "performance": result["performance"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
