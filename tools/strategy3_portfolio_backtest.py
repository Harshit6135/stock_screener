"""Read-only Strategy 3 v4 shared-capital portfolio backtest.

Signals are calculated at the close, buys at the next open, fixed Bollinger
lower-band stops intraday, and unstopped positions exit at the horizon close.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import mean, stdev
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.early_momentum import rank_day
from src.application.early_momentum_rules import V4_RULES
from src.application.positional_trend import valid_bar
from src.indicators.custom.early_momentum import early_momentum_feature_series


@dataclass(frozen=True)
class Policy:
    initial_capital: float = 500_000
    max_positions: int = 15
    holding_sessions: int = 20
    risk_fraction: float = V4_RULES.risk_fraction
    order_cap_fraction: float = V4_RULES.position_cap_fraction
    participation_fraction: float = V4_RULES.participation_fraction
    round_trip_cost_bps: float = V4_RULES.round_trip_cost_bps

    def validate(self) -> None:
        if not (self.initial_capital > 0 and 1 <= self.max_positions <= 500
                and self.holding_sessions >= 1
                and 0 < self.risk_fraction <= 1
                and 0 < self.order_cap_fraction <= 1
                and 0 < self.participation_fraction <= 1
                and 0 <= self.round_trip_cost_bps < 10_000):
            raise ValueError("invalid portfolio policy")


def load_data(database: Path, universe_csv: Path, end_date: str) -> tuple[dict, list[dict], list[str], dict]:
    with universe_csv.open(encoding="utf-8-sig", newline="") as stream:
        members = {row["ISIN Code"] for row in csv.DictReader(stream) if row["Series"] == "EQ"}
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        slots = ",".join("?" for _ in members)
        identities = connection.execute(
            "SELECT instrument_id, isin, symbol FROM reference_instruments "
            f"WHERE exchange='NSE' AND isin IN ({slots}) ORDER BY observed_on DESC", sorted(members)
        ).fetchall()
        chosen = {}
        for row in identities:
            chosen.setdefault(row["isin"], (row["instrument_id"], row["symbol"]))
        benchmark_id = connection.execute(
            "SELECT instrument_id FROM reference_instruments WHERE exchange='NSE' "
            "AND symbol='NIFTY 500' ORDER BY observed_on DESC LIMIT 1"
        ).fetchone()[0]
        ids = [item[0] for item in chosen.values()] + [benchmark_id]
        slots = ",".join("?" for _ in ids)
        histories = {instrument_id: (symbol, []) for instrument_id, symbol in chosen.values()}
        benchmark = []
        for row in connection.execute(
            f"SELECT instrument_id, as_of_date, open, high, low, close, volume FROM market_bars "
            f"WHERE instrument_id IN ({slots}) AND as_of_date BETWEEN '2019-01-01' AND ? "
            "ORDER BY instrument_id, as_of_date", [*ids, end_date]
        ):
            bar = dict(row)
            if row["instrument_id"] == benchmark_id:
                benchmark.append(bar)
            elif row["instrument_id"] in histories:
                histories[row["instrument_id"]][1].append(bar)
    finally:
        connection.close()
    sessions = [str(bar["as_of_date"]) for bar in benchmark]
    coverage = {"constituents": len(members), "matched_isins": len(chosen),
                "stocks_with_bars": sum(bool(bars) for _, bars in histories.values()),
                "last_session": sessions[-1] if sessions else None,
                "historical_membership": "current_constituents_applied_backwards",
                "corporate_action_adjustment": "not_applied"}
    return histories, benchmark, sessions, coverage


def build_signals(histories: dict, benchmark: list[dict], start: str, end: str) -> dict[str, list[dict]]:
    by_day: dict[str, dict] = defaultdict(dict)
    needed = ("residual_score", "relative_volume_50", "bbw_prior_percentile_126",
              "adv30_value", "prior20_volume", "prior252_volume", "lower_bb20_2",
              "cross_ok", "close")
    for instrument_id, (symbol, bars) in histories.items():
        if not bars:
            continue
        for day, feature in early_momentum_feature_series(bars, benchmark).items():
            if start <= day <= end and feature["adv30_value"] > V4_RULES.adv30_minimum:
                by_day[day][instrument_id] = {"symbol": symbol,
                                              **{key: feature[key] for key in needed}}
    signals = {}
    for day, values in by_day.items():
        signals[day] = sorted(
            (item for item in rank_day(values, V4_RULES).values() if item["raw_signal"]),
            key=lambda item: (item["residual_rank"], item["symbol"]),
        )
    return signals


def simulate(histories: dict, sessions: list[str], signals: dict[str, list[dict]],
             *, policy: Policy, start: str, end: str) -> dict:
    policy.validate()
    calendar = [day for day in sessions if start <= day <= end]
    if not calendar:
        raise ValueError("no benchmark sessions in requested range")
    bars = {symbol: {str(b["as_of_date"]): b for b in history}
            for symbol, history in histories.values()}
    fee_fraction = policy.round_trip_cost_bps / 20_000
    cash = policy.initial_capital
    holdings: dict[str, dict] = {}
    last_price: dict[str, float] = {}
    pending: list[dict] = []
    fills, trades, curve = [], [], []
    skips = Counter()
    fees = 0.0

    def sell(day: str, symbol: str, price: float, reason: str) -> None:
        nonlocal cash, fees
        held = holdings.pop(symbol)
        gross = held["shares"] * price
        fee = gross * fee_fraction
        cash += gross - fee
        fees += fee
        trades.append({"symbol": symbol, "entry_date": held["entry_date"],
                       "exit_date": day, "entry_price": held["entry_price"],
                       "exit_price": price, "shares": held["shares"],
                       "holding_sessions": held["holding_sessions"],
                       "exit_reason": reason,
                       "net_pnl": gross - fee - held["entry_cost"]})
        fills.append({"date": day, "symbol": symbol, "side": "SELL", "shares": held["shares"],
                      "price": price, "fee": fee, "reason": reason})

    for day in calendar:
        # Known fixed stops gap out at the open before fresh orders compete for cash.
        for symbol, held in list(holdings.items()):
            bar = bars[symbol].get(day)
            if bar is not None and valid_bar(bar) and float(bar["open"]) <= held["stop"]:
                sell(day, symbol, float(bar["open"]), "stop_gap")

        pending.sort(key=lambda item: (item["residual_rank"], item["symbol"]))
        for signal in pending:
            symbol = signal["symbol"]
            if symbol in holdings:
                skips["already_held"] += 1
                continue
            if len(holdings) >= policy.max_positions:
                skips["max_positions"] += 1
                continue
            bar = bars[symbol].get(day)
            if bar is None or not valid_bar(bar):
                skips["missing_valid_open"] += 1
                continue
            price = float(bar["open"])
            stop = float(signal["lower_bb20_2"])
            if price > signal["close"] * 1.03:
                skips["gap_above_3pct"] += 1
                continue
            if stop <= 0 or price <= stop:
                skips["at_or_below_stop"] += 1
                continue
            equity = cash + sum(h["shares"] * (float(bars[s][day]["open"])
                                if day in bars[s] and valid_bar(bars[s][day]) else last_price[s])
                                for s, h in holdings.items())
            quantity = min(
                math.floor(equity * policy.risk_fraction / (price - stop)),
                math.floor(equity * policy.order_cap_fraction / price),
                math.floor(signal["adv30_value"] * policy.participation_fraction / price),
                math.floor(cash / (price * (1 + fee_fraction))),
            )
            if quantity <= 0:
                skips["zero_size_or_cash"] += 1
                continue
            gross, fee = quantity * price, quantity * price * fee_fraction
            cash -= gross + fee
            fees += fee
            holdings[symbol] = {"shares": quantity, "entry_date": day,
                                "entry_price": price, "entry_cost": gross + fee,
                                "stop": stop, "holding_sessions": 0}
            last_price[symbol] = price
            fills.append({"date": day, "symbol": symbol, "side": "BUY", "shares": quantity,
                          "price": price, "fee": fee, "stop": stop,
                          "signal_date": signal["signal_date"], "equity_at_open": equity})
        pending = []

        for symbol, held in list(holdings.items()):
            bar = bars[symbol].get(day)
            if bar is None or not valid_bar(bar):
                skips["held_missing_valid_bar"] += 1
                continue
            held["holding_sessions"] += 1
            last_price[symbol] = float(bar["close"])
            if float(bar["low"]) <= held["stop"]:
                sell(day, symbol, held["stop"], "intraday_stop")
            elif held["holding_sessions"] >= policy.holding_sessions:
                sell(day, symbol, float(bar["close"]), "horizon_close")
        pending = [{**item, "signal_date": day} for item in signals.get(day, [])]
        equity = cash + sum(h["shares"] * last_price[s] for s, h in holdings.items())
        curve.append({"date": day, "cash": cash, "equity": equity,
                      "positions": len(holdings)})

    final_equity = curve[-1]["equity"]
    peak, max_drawdown = policy.initial_capital, 0.0
    for item in curve:
        peak = max(peak, item["equity"])
        max_drawdown = min(max_drawdown, item["equity"] / peak - 1)
    year_ends = {item["date"][:4]: item["equity"] for item in curve}
    annual_returns, prior = {}, policy.initial_capital
    for year, value in year_ends.items():
        annual_returns[year] = value / prior - 1
        prior = value
    daily = [curve[i]["equity"] / curve[i - 1]["equity"] - 1 for i in range(1, len(curve))]
    volatility = stdev(daily) if len(daily) > 1 else 0.0
    elapsed = (date.fromisoformat(calendar[-1]) - date.fromisoformat(start)).days
    gains = sum(max(0, trade["net_pnl"]) for trade in trades)
    losses = -sum(min(0, trade["net_pnl"]) for trade in trades)
    return {"period": {"requested_start": start, "requested_end": end,
                       "first_session": calendar[0], "last_session": calendar[-1],
                       "session_count": len(calendar)},
            "policy": asdict(policy),
            "performance": {"final_equity": final_equity,
                            "total_return": final_equity / policy.initial_capital - 1,
                            "cagr": (final_equity / policy.initial_capital) ** (365.25 / elapsed) - 1,
                            "max_drawdown": max_drawdown, "annual_returns": annual_returns,
                            "year_end_equity": year_ends, "closed_trades": len(trades),
                            "open_positions": len(holdings),
                            "wins": sum(t["net_pnl"] > 0 for t in trades),
                            "win_rate": sum(t["net_pnl"] > 0 for t in trades) / len(trades) if trades else None,
                            "profit_factor": gains / losses if losses else None,
                            "annualized_daily_volatility": volatility * math.sqrt(252),
                            "sharpe_zero_risk_free": mean(daily) / volatility * math.sqrt(252)
                            if volatility else None,
                            "total_fees": fees},
            "skips": dict(skips), "pending_at_cutoff": [s["symbol"] for s in pending],
            "open_holdings": holdings, "trades": trades, "fills": fills,
            "equity_curve": curve}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "instance/system.db")
    parser.add_argument("--universe-csv", type=Path, default=ROOT / "ind_nifty500list.csv")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--end-date", default=datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat())
    parser.add_argument("--initial-capital", type=float, default=500_000)
    parser.add_argument("--max-positions", type=int, default=15)
    parser.add_argument("--holding-sessions", type=int, default=20)
    args = parser.parse_args(argv)
    policy = Policy(initial_capital=args.initial_capital, max_positions=args.max_positions,
                    holding_sessions=args.holding_sessions)
    histories, benchmark, sessions, coverage = load_data(
        args.database, args.universe_csv, args.end_date)
    signals = build_signals(histories, benchmark, args.start_date, args.end_date)
    result = simulate(histories, sessions, signals, policy=policy,
                      start=args.start_date, end=args.end_date)
    result["data"] = coverage
    result["signal_count"] = sum(map(len, signals.values()))
    result["limitations"] = [
        "current Nifty 500 constituents applied retrospectively (survivorship bias)",
        "raw OHLCV without split/bonus adjustment; differs from Strategy 3 event study",
        "daily bars cannot establish intraday stop fill quality or upper-circuit availability",
        "fixed 20-session portfolio exit is an added simulation assumption",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({"output": str(args.output), "period": result["period"],
                      "signals": result["signal_count"],
                      "performance": result["performance"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
