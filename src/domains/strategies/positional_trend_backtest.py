"""Positional trend portfolio policy and deterministic next-open replay."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime
from statistics import mean, median, stdev
from zoneinfo import ZoneInfo

from .positional_trend import feature_series, valid_bar


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
        numeric = (
            self.initial_capital,
            self.max_name_fraction,
            self.nominal_risk_fraction,
            self.adv_participation_fraction,
            self.round_trip_cost_bps,
        )
        if (
            any(isinstance(value, bool) or not math.isfinite(value) for value in numeric)
            or isinstance(self.max_positions, bool)
            or not isinstance(self.max_positions, int)
            or not (
                self.initial_capital > 0
                and 1 <= self.max_positions <= 500
                and 0 < self.max_name_fraction <= 1
                and 0 < self.nominal_risk_fraction <= 1
                and 0 < self.adv_participation_fraction <= 1
                and 0 <= self.round_trip_cost_bps < 10_000
                and isinstance(self.enable_pyramiding, bool)
            )
        ):
            raise ValueError("invalid portfolio policy")


def _equity_at_open(
    cash: float, holdings: dict, bars: dict, day: str, last_price: dict[str, float]
) -> float:
    return cash + sum(
        held["shares"]
        * (
            float(bars[symbol][day]["open"])
            if day in bars[symbol] and valid_bar(bars[symbol][day])
            else last_price[symbol]
        )
        for symbol, held in holdings.items()
    )


def simulate(
    histories: dict,
    sessions: list[str],
    *,
    policy: Policy,
    start_date: str = "2022-01-01",
    end_date: str | None = None,
    rules: dict | None = None,
    membership_by_day: dict | None = None,
) -> dict:
    policy.validate()
    end_date = end_date or datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    calendar = [day for day in sessions if start_date <= day <= end_date]
    if not calendar:
        raise ValueError("no market sessions in requested backtest range")
    next_session = {day: sessions[index + 1] for index, day in enumerate(sessions[:-1])}
    execution_calendar = list(calendar)
    extra_session = next_session.get(calendar[-1])
    if membership_by_day is not None and extra_session is not None:
        execution_calendar.append(extra_session)
    if membership_by_day is not None and any(day not in membership_by_day for day in calendar):
        raise ValueError("as-of universe membership is missing for a replay session")
    bars = {}
    features_by_day = defaultdict(dict)
    for symbol, history in histories.values():
        bars[symbol] = {str(bar["as_of_date"]): bar for bar in history}
        decision_history = [bar for bar in history if str(bar["as_of_date"]) <= end_date]
        for item in feature_series(
            decision_history, [day for day in sessions if day <= end_date], symbol, rules
        ):
            if start_date <= item["signal_date"] <= end_date and (
                item["filtered"] or item["exit_signal"]
            ):
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
    pending_exit_details = {}
    exit_records = []
    holdings_at_end = None
    fees_at_end = None
    for day in execution_calendar:
        # Previous close's exits execute before competing entries at today's open.
        for symbol, trigger_day in list(pending_exits.items()):
            detail = pending_exit_details.get(symbol)
            if detail is not None and detail["target_execution_session"] != day:
                continue
            bar = bars[symbol].get(day)
            if bar is None or not valid_bar(bar):
                if detail is not None:
                    detail["fill_status"] = "MISSING_OPEN"
                    skips["missing_target_session_open"] += 1
                else:
                    skips["exit_waiting_for_valid_open"] += 1
                continue
            holding = holdings.pop(symbol)
            price = float(bar["open"])
            gross = holding["shares"] * price
            fee = gross * fee_fraction
            cash += gross - fee
            total_fees += fee
            trade = {
                "symbol": symbol,
                "entry_date": holding["entry_date"],
                "entry_price": holding["entry_price"],
                "average_entry_price": holding["average_price"],
                "pyramid_adds": holding["pyramid_adds"],
                "exit_date": day,
                "exit_price": price,
                "shares": holding["shares"],
                "entry_signal_date": holding["signal_date"],
                "exit_signal_date": trigger_day,
                "net_pnl": gross - fee - holding["entry_total_cost"],
                "net_return": (gross - fee) / holding["entry_total_cost"] - 1,
            }
            trades.append(trade)
            fills.append(
                {
                    "date": day,
                    "symbol": symbol,
                    "side": "SELL",
                    "shares": holding["shares"],
                    "price": price,
                    "fee": fee,
                    "trigger_date": trigger_day,
                }
            )
            if detail is not None:
                detail.update(
                    {
                        "fill_status": "FILLED",
                        "execution_date": day,
                        "price_source": bar.get("snapshot_id"),
                        "execution_price": price,
                    }
                )
                fills[-1].update(detail)
                trades[-1].update(detail)
                exit_records.append(dict(detail, symbol=symbol))
                del pending_exit_details[symbol]
            del pending_exits[symbol]

        # The one extra session only settles previously decided exits. Its
        # price never feeds rankings, entries or the requested period valuation.
        if day > end_date:
            continue
        # Every qualifying signal competes in the same ranking, including held names.
        pending_candidates.sort(key=lambda item: (-item["adx14"], -item["adv30"], item["symbol"]))
        for signal in pending_candidates:
            symbol = signal["symbol"]
            if membership_by_day is not None and symbol not in membership_by_day[day]["symbols"]:
                skips["outside_as_of_universe"] += 1
                continue
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
                holdings[symbol] = {
                    "shares": quantity,
                    "entry_date": day,
                    "entry_price": price,
                    "average_price": price,
                    "entry_total_cost": gross + fee,
                    "signal_date": signal["signal_date"],
                    "pyramid_adds": 0,
                    "lots": [
                        {"entry_date": day, "entry_price": price, "shares": quantity, "fee": fee}
                    ],
                }
            else:
                old_shares = holding["shares"]
                holding["shares"] += quantity
                holding["average_price"] = (
                    holding["average_price"] * old_shares + gross
                ) / holding["shares"]
                holding["entry_total_cost"] += gross + fee
                holding["pyramid_adds"] += 1
                holding["lots"].append(
                    {"entry_date": day, "entry_price": price, "shares": quantity, "fee": fee}
                )
            last_price[symbol] = price
            fills.append(
                {
                    "date": day,
                    "symbol": symbol,
                    "side": "PYRAMID_ADD" if holding is not None else "BUY",
                    "shares": quantity,
                    "price": price,
                    "fee": fee,
                    "trigger_date": signal["signal_date"],
                    "stop_anchor": stop,
                    "equity_at_open": equity,
                    "position_nominal_risk_after": quantity * (price - stop),
                    "order_fraction_of_equity": gross / equity,
                    "name_fraction_after": holdings[symbol]["shares"] * price / equity,
                }
            )
        pending_candidates = []

        current_features = features_by_day.get(day, {})
        for symbol in holdings:
            bar = bars[symbol].get(day)
            if bar is not None and valid_bar(bar):
                last_price[symbol] = float(bar["close"])
            feature = current_features.get(symbol)
            excluded = (
                membership_by_day is not None and symbol not in membership_by_day[day]["symbols"]
            )
            if (excluded or feature and feature["exit_signal"]) and symbol not in pending_exits:
                pending_exits[symbol] = day
                if membership_by_day is not None:
                    target = next_session.get(day)
                    pending_exit_details[symbol] = {
                        "decision_date": day,
                        "target_execution_session": target,
                        "universe_snapshot_id": membership_by_day[day]["snapshot_id"],
                        "exit_reason": "universe_exit" if excluded else "daily_signal",
                        "price_source": None,
                        "fill_status": "PENDING" if target is not None else "MISSING_SESSION",
                    }
        pending_candidates = [
            item
            for symbol, item in current_features.items()
            if item["filtered"]
            and symbol not in pending_exits
            and (membership_by_day is None or symbol in membership_by_day[day]["symbols"])
            and (symbol not in holdings or policy.enable_pyramiding)
        ]
        equity = cash + sum(h["shares"] * last_price[s] for s, h in holdings.items())
        curve.append({"date": day, "equity": equity, "cash": cash, "positions": len(holdings)})
        if day == calendar[-1]:
            holdings_at_end = deepcopy(holdings)
            fees_at_end = total_fees

    period_trades = [trade for trade in trades if trade["exit_date"] <= end_date]
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
    cagr = (
        (final_equity / policy.initial_capital) ** (365.25 / elapsed_days) - 1
        if elapsed_days > 0
        else None
    )
    daily_returns = [curve[i]["equity"] / curve[i - 1]["equity"] - 1 for i in range(1, len(curve))]
    daily_vol = stdev(daily_returns) if len(daily_returns) > 1 else 0.0
    gains = sum(max(0.0, trade["net_pnl"]) for trade in period_trades)
    losses = -sum(min(0.0, trade["net_pnl"]) for trade in period_trades)
    return {
        "period": {
            "requested_start": start_date,
            "requested_end": end_date,
            "first_session": calendar[0],
            "last_session": calendar[-1],
            "session_count": len(calendar),
        },
        "policy": asdict(policy),
        "performance": {
            "final_equity": final_equity,
            "total_return": final_equity / policy.initial_capital - 1,
            "cagr": cagr,
            "max_drawdown": max_drawdown,
            "annual_returns": annual_returns,
            "closed_trades": len(period_trades),
            "open_positions": len(holdings_at_end),
            "pyramid_add_fills": sum(fill["side"] == "PYRAMID_ADD" for fill in fills),
            "wins": sum(t["net_pnl"] > 0 for t in period_trades),
            "win_rate": sum(t["net_pnl"] > 0 for t in period_trades) / len(period_trades)
            if period_trades
            else None,
            "mean_closed_trade_return": mean(t["net_return"] for t in period_trades)
            if period_trades
            else None,
            "median_closed_trade_return": median(t["net_return"] for t in period_trades)
            if period_trades
            else None,
            "profit_factor": gains / losses if losses else None,
            "annualized_daily_volatility": daily_vol * math.sqrt(252),
            "sharpe_zero_risk_free": (
                mean(daily_returns) / daily_vol * math.sqrt(252) if daily_vol > 0 else None
            ),
            "average_positions": mean(item["positions"] for item in curve),
            "total_fees": fees_at_end,
        },
        "execution_skips": dict(skips),
        "pending_exits": pending_exits,
        "pending_candidates_at_data_end": [item["symbol"] for item in pending_candidates],
        "open_holdings": holdings_at_end,
        "holdings_after_exit_session": holdings,
        "exit_records": exit_records
        + [dict(detail, symbol=symbol) for symbol, detail in pending_exit_details.items()],
        "trades": trades,
        "fills": fills,
        "equity_curve": curve,
    }
