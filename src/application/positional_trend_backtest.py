"""Shared Strategy 4 market loaders and next-open portfolio replay."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median, stdev
from zoneinfo import ZoneInfo

from src.application.positional_trend import feature_series, valid_bar


def load_data(database: Path, universe_csv: Path, *, end_date: str | None = None,
              include_be: bool = False) -> tuple[dict, list[str], dict]:
    if not database.is_file() or not universe_csv.is_file():
        raise ValueError("database and constituent CSV must exist")
    with universe_csv.open(encoding="utf-8-sig", newline="") as stream:
        constituent_rows = list(csv.DictReader(stream))
        accepted_series = {"EQ", "BE"} if include_be else {"EQ"}
        members = {row["ISIN Code"] for row in constituent_rows if row["Series"] in accepted_series}
        be_members = {row["ISIN Code"] for row in constituent_rows
                      if include_be and row["Series"] == "BE"}
    if not members:
        raise ValueError("constituent CSV contains no EQ members")
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in members)
        identities = connection.execute(
            f"SELECT instrument_id, isin, symbol, observed_on, exchange FROM reference_instruments "
            f"WHERE exchange IN ('NSE', 'BSE') AND isin IN ({placeholders}) "
            f"ORDER BY isin, CASE exchange WHEN 'NSE' THEN 0 ELSE 1 END, observed_on DESC, symbol",
            sorted(members),
        ).fetchall()
        chosen = {}
        chosen_exchanges = {}
        for row in identities:
            if row["exchange"] == "BSE" and row["isin"] not in be_members:
                continue
            if row["isin"] not in chosen:
                chosen[row["isin"]] = (row["instrument_id"], row["symbol"])
                chosen_exchanges[row["isin"]] = row["exchange"]
        if not chosen:
            raise ValueError("no constituent EQ members match NSE reference instruments")
        ids = [item[0] for item in chosen.values()]
        symbols = {item[0]: item[1] for item in chosen.values()}
        placeholders = ",".join("?" for _ in ids)
        cutoff = end_date or datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        rows = connection.execute(
            f"SELECT instrument_id, as_of_date, open, high, low, close, volume "
            f"FROM market_bars WHERE instrument_id IN ({placeholders}) "
            f"AND as_of_date BETWEEN '2021-01-01' AND ? "
            f"ORDER BY instrument_id, as_of_date",
            [*ids, cutoff],
        )
        histories: dict[str, tuple[str, list[dict]]] = {}
        all_sessions = set()
        bar_count = 0
        for row in rows:
            instrument_id = row["instrument_id"]
            if instrument_id not in histories:
                histories[instrument_id] = (symbols[instrument_id], [])
            bar = dict(row)
            histories[instrument_id][1].append(bar)
            all_sessions.add(bar["as_of_date"])
            bar_count += 1
    finally:
        connection.close()
    sessions = sorted(all_sessions)
    coverage = {
        "universe_source": "constituent_csv", "universe_csv": universe_csv.name,
        "constituent_eq_count": sum(row["Series"] == "EQ" for row in constituent_rows),
        "included_member_count": len(members), "included_series": sorted(accepted_series),
        "matched_isin_count": len(chosen),
        "matched_members_by_exchange": dict(Counter(chosen_exchanges.values())),
        "be_price_source": "NSE preferred; BSE fallback by identical ISIN when NSE is absent",
        "instruments_with_bars": len(histories), "bar_count": bar_count,
        "session_count": len(sessions), "first_session": sessions[0] if sessions else None,
        "last_session": sessions[-1] if sessions else None,
        "missing_isins": sorted(members - chosen.keys()),
        "universe_csv_sha256": hashlib.sha256(universe_csv.read_bytes()).hexdigest(),
        "historical_membership": "current_constituents_applied_backwards",
        "corporate_action_adjustment": "not_applied_per_research_scope",
    }
    return histories, sessions, coverage


def load_market_cap_universe(database: Path, *, end_date: str) -> tuple[dict, list[str], dict]:
    """Use the current application universe retrospectively, across NSE and BSE."""
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        members = [dict(row) for row in connection.execute(
            "SELECT u.*, r.symbol AS current_symbol FROM universe_membership u "
            "JOIN reference_instruments r ON r.instrument_id=u.instrument_id "
            "WHERE u.exchange IN ('NSE', 'BSE') AND u.last_market_cap >= 5000000000 "
            "ORDER BY u.exchange, u.isin")]
        if not members:
            raise ValueError("application market-cap universe is empty")
        symbols = [row["current_symbol"] for row in members]
        if len(set(symbols)) != len(symbols):
            raise ValueError("duplicate symbols across exchanges require explicit identity labels")
        histories = {row["instrument_id"]: (row["current_symbol"], []) for row in members}
        slots = ",".join("?" for _ in histories)
        count = 0
        for row in connection.execute(
            f"SELECT instrument_id, as_of_date, open, high, low, close, volume FROM market_bars "
            f"WHERE instrument_id IN ({slots}) AND as_of_date BETWEEN '2021-01-01' AND ? "
            "ORDER BY instrument_id, as_of_date", [*histories, end_date]):
            bar = dict(row)
            instrument_id = bar.pop("instrument_id")
            histories[instrument_id][1].append(bar)
            count += 1
        benchmark = connection.execute(
            "SELECT instrument_id FROM reference_instruments WHERE exchange='NSE' "
            "AND symbol='NIFTY 500' ORDER BY observed_on DESC LIMIT 1").fetchone()
        if benchmark is None:
            raise ValueError("Nifty 500 benchmark calendar is missing")
        sessions = [row[0] for row in connection.execute(
            "SELECT as_of_date FROM market_bars WHERE instrument_id=? "
            "AND as_of_date BETWEEN '2021-01-01' AND ? ORDER BY as_of_date",
            (benchmark[0], end_date))]
        coverage = {"universe_source": "application_market_cap_universe",
                    "minimum_market_cap_crore": 500, "members": len(members),
                    "members_by_exchange": dict(Counter(row["exchange"] for row in members)),
                    "instruments_with_bars": sum(bool(bars) for _, bars in histories.values()),
                    "bar_count": count, "session_count": len(sessions),
                    "calendar": "NIFTY 500 stored sessions",
                    "first_session": sessions[0] if sessions else None,
                    "last_session": sessions[-1] if sessions else None,
                    "membership_snapshot_dates": sorted({row["snapshot_date"] for row in members}),
                    "membership_sha256": hashlib.sha256(
                        json.dumps(members, sort_keys=True).encode()).hexdigest(),
                    "historical_membership": "current_market_cap_members_applied_backwards",
                    "corporate_action_adjustment": "not_applied_per_research_scope"}
        return histories, sessions, coverage
    finally:
        connection.close()


@dataclass(frozen=True)
class Policy:
    initial_capital: float = 500_000.0
    max_positions: int = 15
    max_name_fraction: float = 0.10
    nominal_risk_fraction: float = 0.01
    adv_participation_fraction: float = 0.01
    round_trip_cost_bps: float = 50.0
    enable_pyramiding: bool = False

    def validate(self) -> None:
        numeric = (self.initial_capital, self.max_name_fraction, self.nominal_risk_fraction,
                   self.adv_participation_fraction, self.round_trip_cost_bps)
        if (any(isinstance(value, bool) or not math.isfinite(value) for value in numeric)
                or isinstance(self.max_positions, bool) or not isinstance(self.max_positions, int)
                or not (self.initial_capital > 0 and 1 <= self.max_positions <= 500
                and 0 < self.max_name_fraction <= 1
                and 0 < self.nominal_risk_fraction <= 1
                and 0 < self.adv_participation_fraction <= 1
                and 0 <= self.round_trip_cost_bps < 10_000
                and isinstance(self.enable_pyramiding, bool))):
            raise ValueError("invalid portfolio policy")


def _equity_at_open(cash: float, holdings: dict, bars: dict, day: str,
                    last_price: dict[str, float]) -> float:
    return cash + sum(
        held["shares"] * (
            float(bars[symbol][day]["open"])
            if day in bars[symbol] and valid_bar(bars[symbol][day])
            else last_price[symbol])
        for symbol, held in holdings.items()
    )


def simulate(histories: dict, sessions: list[str], *, policy: Policy,
             start_date: str = "2022-01-01", end_date: str | None = None,
             rules: dict | None = None) -> dict:
    policy.validate()
    end_date = end_date or datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    calendar = [day for day in sessions if start_date <= day <= end_date]
    if not calendar:
        raise ValueError("no market sessions in requested backtest range")
    bars = {}
    features_by_day = defaultdict(dict)
    for symbol, history in histories.values():
        bars[symbol] = {str(bar["as_of_date"]): bar for bar in history}
        for item in feature_series(history, sessions, symbol, rules):
            if (start_date <= item["signal_date"] <= end_date
                    and (item["filtered"] or item["exit_signal"])):
                features_by_day[item["signal_date"]][symbol] = item

    fee_fraction = policy.round_trip_cost_bps / 20_000
    cash = policy.initial_capital
    holdings: dict[str, dict] = {}
    last_price: dict[str, float] = {}
    pending_exits: dict[str, str] = {}
    pending_candidates: list[dict] = []
    trades: list[dict] = []
    fills: list[dict] = []
    curve: list[dict] = []
    skips = Counter()
    total_fees = 0.0
    for day in calendar:
        # Previous close's exits execute before competing entries at today's open.
        for symbol, trigger_day in list(pending_exits.items()):
            bar = bars[symbol].get(day)
            if bar is None or not valid_bar(bar):
                skips["exit_waiting_for_valid_open"] += 1
                continue
            holding = holdings.pop(symbol)
            price = float(bar["open"])
            gross = holding["shares"] * price
            fee = gross * fee_fraction
            cash += gross - fee
            total_fees += fee
            trade = {"symbol": symbol, "entry_date": holding["entry_date"],
                     "entry_price": holding["entry_price"],
                     "average_entry_price": holding["average_price"],
                     "pyramid_adds": holding["pyramid_adds"], "exit_date": day,
                     "exit_price": price, "shares": holding["shares"],
                     "entry_signal_date": holding["signal_date"],
                     "exit_signal_date": trigger_day,
                     "net_pnl": gross - fee - holding["entry_total_cost"],
                     "net_return": (gross - fee) / holding["entry_total_cost"] - 1}
            trades.append(trade)
            fills.append({"date": day, "symbol": symbol, "side": "SELL", "shares": holding["shares"],
                          "price": price, "fee": fee, "trigger_date": trigger_day})
            del pending_exits[symbol]

        # Every qualifying signal competes in the same ranking, including held names.
        pending_candidates.sort(key=lambda item: (-item["adx14"], -item["adv30"], item["symbol"]))
        for signal in pending_candidates:
            symbol = signal["symbol"]
            holding = holdings.get(symbol)
            if symbol in pending_exits:
                skips["exiting"] += 1
                continue
            if holding is not None and not policy.enable_pyramiding:
                continue
            if holding is None and len(holdings) >= policy.max_positions:
                skips["max_positions"] += 1
                continue
            bar = bars[symbol].get(day)
            if bar is None or not valid_bar(bar):
                skips["missing_valid_open"] += 1
                continue
            price = float(bar["open"])
            stop = signal["initial_stop_anchor"]
            if price > signal["close"] * 1.03:
                skips["gap_above_3pct"] += 1
                continue
            if stop <= 0 or price <= stop:
                skips["at_or_below_stop"] += 1
                continue
            if holding is not None and stop <= max(lot["entry_price"] for lot in holding["lots"]):
                skips["pyramid_prior_risk_not_zero"] += 1
                continue
            equity = _equity_at_open(cash, holdings, bars, day, last_price)
            quantity = min(
                math.floor(equity * policy.nominal_risk_fraction / (price - stop)),
                math.floor(equity * policy.max_name_fraction / price),
                math.floor(signal["adv30"] * policy.adv_participation_fraction / price),
                math.floor(cash / (price * (1 + fee_fraction))),
            )
            if quantity <= 0:
                skips["zero_size_or_cash"] += 1
                continue
            gross = quantity * price
            fee = gross * fee_fraction
            cash -= gross + fee
            total_fees += fee
            if holding is None:
                holdings[symbol] = {"shares": quantity, "entry_date": day,
                                    "entry_price": price, "average_price": price,
                                    "entry_total_cost": gross + fee,
                                    "signal_date": signal["signal_date"],
                                    "pyramid_adds": 0,
                                    "lots": [{"entry_date": day, "entry_price": price,
                                              "shares": quantity, "fee": fee}]}
            else:
                old_shares = holding["shares"]
                holding["shares"] += quantity
                holding["average_price"] = (holding["average_price"] * old_shares + gross) / holding["shares"]
                holding["entry_total_cost"] += gross + fee
                holding["pyramid_adds"] += 1
                holding["lots"].append({"entry_date": day, "entry_price": price,
                                        "shares": quantity, "fee": fee})
            last_price[symbol] = price
            fills.append({"date": day, "symbol": symbol,
                          "side": "PYRAMID_ADD" if holding is not None else "BUY", "shares": quantity,
                          "price": price, "fee": fee, "trigger_date": signal["signal_date"],
                          "stop_anchor": stop, "equity_at_open": equity,
                          "position_nominal_risk_after": quantity * (price - stop),
                          "order_fraction_of_equity": gross / equity,
                          "name_fraction_after": holdings[symbol]["shares"] * price / equity})
        pending_candidates = []

        current_features = features_by_day.get(day, {})
        for symbol in holdings:
            bar = bars[symbol].get(day)
            if bar is not None and valid_bar(bar):
                last_price[symbol] = float(bar["close"])
            feature = current_features.get(symbol)
            if feature and feature["exit_signal"] and symbol not in pending_exits:
                pending_exits[symbol] = day
        pending_candidates = [item for symbol, item in current_features.items()
                              if item["filtered"] and symbol not in pending_exits
                              and (symbol not in holdings or policy.enable_pyramiding)]
        equity = cash + sum(h["shares"] * last_price[s] for s, h in holdings.items())
        curve.append({"date": day, "equity": equity, "cash": cash,
                      "positions": len(holdings)})

    final_equity = curve[-1]["equity"]
    peak = policy.initial_capital
    max_drawdown = 0.0
    for item in curve:
        peak = max(peak, item["equity"])
        max_drawdown = min(max_drawdown, item["equity"] / peak - 1)
    year_ends = {}
    annual_returns = {}
    prior = policy.initial_capital
    for item in curve:
        year_ends[item["date"][:4]] = item["equity"]
    for year, equity in year_ends.items():
        annual_returns[year] = equity / prior - 1
        prior = equity
    elapsed_days = (date.fromisoformat(calendar[-1]) - date.fromisoformat(start_date)).days
    cagr = (final_equity / policy.initial_capital) ** (365.25 / elapsed_days) - 1 if elapsed_days > 0 else None
    daily_returns = [curve[i]["equity"] / curve[i - 1]["equity"] - 1
                     for i in range(1, len(curve))]
    daily_vol = stdev(daily_returns) if len(daily_returns) > 1 else 0.0
    gains = sum(max(0.0, trade["net_pnl"]) for trade in trades)
    losses = -sum(min(0.0, trade["net_pnl"]) for trade in trades)
    return {"period": {"requested_start": start_date, "requested_end": end_date,
                       "first_session": calendar[0], "last_session": calendar[-1],
                       "session_count": len(calendar)},
            "policy": asdict(policy),
            "performance": {"final_equity": final_equity,
                            "total_return": final_equity / policy.initial_capital - 1,
                            "cagr": cagr, "max_drawdown": max_drawdown,
                            "annual_returns": annual_returns,
                            "closed_trades": len(trades),
                            "open_positions": len(holdings),
                            "pyramid_add_fills": sum(fill["side"] == "PYRAMID_ADD" for fill in fills),
                            "wins": sum(t["net_pnl"] > 0 for t in trades),
                            "win_rate": sum(t["net_pnl"] > 0 for t in trades) / len(trades) if trades else None,
                            "mean_closed_trade_return": mean(t["net_return"] for t in trades) if trades else None,
                            "median_closed_trade_return": median(t["net_return"] for t in trades) if trades else None,
                            "profit_factor": gains / losses if losses else None,
                            "annualized_daily_volatility": daily_vol * math.sqrt(252),
                            "sharpe_zero_risk_free": (mean(daily_returns) / daily_vol * math.sqrt(252)
                                                      if daily_vol > 0 else None),
                            "average_positions": mean(item["positions"] for item in curve),
                            "total_fees": total_fees},
            "execution_skips": dict(skips), "pending_exits": pending_exits,
            "pending_candidates_at_data_end": [item["symbol"] for item in pending_candidates],
            "open_holdings": holdings, "trades": trades, "fills": fills,
            "equity_curve": curve}


def benchmark_price_return(database: Path, first_session: str, last_session: str) -> dict | None:
    """NIFTY 500 price-index comparison; dividends are not included."""
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT instrument_id FROM reference_instruments "
            "WHERE exchange='NSE' AND symbol='NIFTY 500' ORDER BY observed_on DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        bars = connection.execute(
            "SELECT as_of_date, close FROM market_bars WHERE instrument_id=? "
            "AND as_of_date BETWEEN ? AND ? ORDER BY as_of_date",
            (row[0], first_session, last_session),
        ).fetchall()
        if len(bars) < 2:
            return None
        first, last = bars[0], bars[-1]
        total = float(last[1]) / float(first[1]) - 1
        elapsed = (date.fromisoformat(last[0]) - date.fromisoformat(first[0])).days
        return {"name": "NIFTY 500 price index", "first_date": first[0],
                "last_date": last[0], "first_close": float(first[1]),
                "last_close": float(last[1]), "total_return": total,
                "cagr": (1 + total) ** (365.25 / elapsed) - 1 if elapsed > 0 else None,
                "dividends_included": False}
    finally:
        connection.close()


