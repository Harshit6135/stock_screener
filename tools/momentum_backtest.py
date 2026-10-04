"""Run Strategy 1 using the application BacktestJobs engine."""
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

from src.gates.composition import ApplicationServices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "instance/stock_screener.db")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--end-date", default=datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat())
    parser.add_argument("--initial-capital", type=float, default=500_000)
    parser.add_argument("--max-positions", type=int, default=15)
    parser.add_argument("--slippage-bps", type=float, default=0)
    parser.add_argument("--fee-bps", type=float, default=0)
    parser.add_argument("--tax-bps", type=float, default=0)
    args = parser.parse_args(argv)

    services = ApplicationServices.create(args.database.parent)
    payload = {
        "strategy_id": "momentum",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "starting_cash": args.initial_capital,
        "max_positions": args.max_positions,
        "slippage_bps": args.slippage_bps,
        "fee_bps": args.fee_bps,
        "tax_bps": args.tax_bps,
    }
    result = services.backtests.execute(payload)
    
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "run_id": result["run_id"], "metrics": result["metrics"]}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
