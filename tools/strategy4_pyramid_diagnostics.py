"""Measure pyramid timing and closed add-lot outcomes from Strategy 4 fill ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median


def diagnose(result: dict) -> dict:
    day_index = {item["date"]: i for i, item in enumerate(result["equity_curve"])}
    active = {}
    adds = []
    closed_adds = []
    for fill in result["fills"]:
        symbol = fill["symbol"]
        if fill["side"] == "BUY":
            active[symbol] = [fill]
        elif fill["side"] == "PYRAMID_ADD":
            lots = active[symbol]
            first, last = lots[0], lots[-1]
            record = {**fill,
                      "sessions_after_initial": day_index[fill["date"]] - day_index[first["date"]],
                      "sessions_after_previous": day_index[fill["date"]] - day_index[last["date"]],
                      "rise_from_initial": fill["price"] / first["price"] - 1,
                      "notional": fill["shares"] * fill["price"],
                      "notional_vs_initial": (fill["shares"] * fill["price"]
                                              / (first["shares"] * first["price"]))}
            adds.append(record)
            lots.append(record)
        elif fill["side"] == "SELL":
            lots = active.pop(symbol)
            assert sum(lot["shares"] for lot in lots) == fill["shares"]
            for lot in lots[1:]:
                exit_fee = fill["fee"] * lot["shares"] / fill["shares"]
                pnl = lot["shares"] * (fill["price"] - lot["price"]) - lot["fee"] - exit_fee
                closed_adds.append({**lot, "exit_date": fill["date"], "net_pnl": pnl,
                                    "net_return": pnl / (lot["notional"] + lot["fee"])})
    return {
        "add_count": len(adds), "closed_add_count": len(closed_adds),
        "open_add_count": len(adds) - len(closed_adds),
        "median_sessions_after_initial": median(a["sessions_after_initial"] for a in adds) if adds else None,
        "median_sessions_after_previous": median(a["sessions_after_previous"] for a in adds) if adds else None,
        "median_rise_from_initial": median(a["rise_from_initial"] for a in adds) if adds else None,
        "median_notional": median(a["notional"] for a in adds) if adds else None,
        "median_notional_vs_initial": median(a["notional_vs_initial"] for a in adds) if adds else None,
        "single_share_add_count": sum(a["shares"] == 1 for a in adds),
        "adds_below_one_percent_equity": sum(a["order_fraction_of_equity"] < .01 for a in adds),
        "closed_add_net_pnl": sum(a["net_pnl"] for a in closed_adds),
        "closed_add_win_rate": sum(a["net_pnl"] > 0 for a in closed_adds) / len(closed_adds) if closed_adds else None,
        "closed_add_median_return": median(a["net_return"] for a in closed_adds) if closed_adds else None,
        "risk_gate_skips": result["execution_skips"].get("pyramid_prior_risk_not_zero", 0),
        "interpretation": "Closed add-lot P&L is attribution, not the causal on/off portfolio difference; open add lots are excluded from this P&L.",
        "adds": adds, "closed_adds": closed_adds,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = {path.name: diagnose(json.loads(path.read_text(encoding="utf-8"))) for path in args.results}
    args.output.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for name, diagnostic in output.items():
        print(json.dumps({"file": name, **{k: v for k, v in diagnostic.items() if k not in {"adds", "closed_adds"}}}))


if __name__ == "__main__":
    main()
