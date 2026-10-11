"""Read-only ATR stop estimates for holdings without strategy stop projections."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import isfinite
from zoneinfo import ZoneInfo

import pandas as pd

from src.domains.indicators.momentum_quality import average_true_range
from src.domains.portfolio_engine.api import PortfolioPolicy
from src.domains.strategies import valid_bar


def completed_week_end(as_of):
    """Last Friday whose market close has completed by the valuation time."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    completed = min(as_of, now.date())
    if completed == now.date() and now.time() < time(15, 30):
        completed -= timedelta(days=1)
    return completed - timedelta(days=(completed.weekday() - 4) % 7)


def latest_saved_stops(projections, as_of):
    """Choose the latest dated ATR projection for each instrument."""
    saved = {}
    for row in sorted(projections, key=lambda row: str(row["action_date"]), reverse=True):
        if row.get("stop_model") != "ATR" or str(row["action_date"]) > as_of.isoformat():
            continue
        for position in row["positions"]:
            saved.setdefault(
                str(position["instrument_id"]),
                {
                    "stop": Decimal(str(position["current_trailing_stop"])),
                    "date": str(
                        row.get("as_of_date")
                        or completed_week_end(date.fromisoformat(str(row["action_date"])))
                    ),
                },
            )
    return saved


def portfolio_stops(market, lots, as_of, saved=None):
    saved = saved or {}
    # ATR uses daily bars, but the stop only ratchets on a completed week's close.
    weekly_completed = completed_week_end(as_of)
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    completed = min(as_of, now.date())
    if completed == now.date() and now.time() < time(15, 30):
        completed -= timedelta(days=1)
    multiplier = PortfolioPolicy(1, Decimal(0)).atr_multiplier
    by_instrument = {}
    for lot in lots:
        by_instrument.setdefault(lot.instrument_id, []).append(lot)
    result = {}
    for instrument_id, instrument_lots in by_instrument.items():
        opened = min(lot.opened_on for lot in instrument_lots)
        opening_lots = [lot for lot in instrument_lots if lot.opened_on == opened]
        entry_cost = sum(
            (lot.unit_cost.amount * lot.remaining_units.units for lot in opening_lots), Decimal(0)
        ) / sum(lot.remaining_units.units for lot in opening_lots)
        bars = []
        end = completed
        while end >= date.min:
            batch = market.bars(instrument_id, date.min, end, limit=1000)
            bars = batch + bars
            if len(batch) < 1000:
                break
            first = date.fromisoformat(batch[0]["as_of_date"])
            if first == date.min:
                break
            end = first - timedelta(days=1)
        bars = [bar for bar in bars if valid_bar(bar)]
        prior = saved.get(instrument_id)
        row = {
            "current_trailing_stop": prior["stop"] if prior else None,
            "entry_stop": None,
            "atr": None,
            "risk_date": prior["date"] if prior else None,
            "risk_basis": "persisted_atr_projection" if prior else "ATR14_2x_weekly_close",
            "risk_note": None,
            "weekly_close": None,
            "weekly_close_date": None,
        }
        if len(bars) < 14:
            row["risk_note"] = "At least 14 completed OHLC sessions are required for ATR."
            result[instrument_id] = row
            continue
        frame = pd.DataFrame(bars)
        for column in ("high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column])
        atr = average_true_range(frame)
        week_closes = {}
        for i, bar in enumerate(bars):
            session = date.fromisoformat(bar["as_of_date"])
            if session.weekday() < 5 and session <= weekly_completed:
                week_closes[session.isocalendar()[:2]] = i
        weekly_indices = set(week_closes.values())
        if weekly_indices:
            last = bars[max(weekly_indices)]
            row["weekly_close"] = Decimal(str(last["close"]))
            row["weekly_close_date"] = last["as_of_date"]
        prior_entry = [
            i
            for i, bar in enumerate(bars)
            if bar["as_of_date"] < opened.isoformat() and pd.notna(atr.iloc[i])
        ]
        after_entry = [
            i
            for i, bar in enumerate(bars)
            if bar["as_of_date"] >= opened.isoformat() and pd.notna(atr.iloc[i])
        ]
        if prior_entry:
            row["entry_stop"] = max(
                Decimal(0), entry_cost - multiplier * Decimal(str(atr.iloc[prior_entry[-1]]))
            )
        elif after_entry:
            row["entry_stop"] = max(
                Decimal(0), entry_cost - multiplier * Decimal(str(atr.iloc[after_entry[0]]))
            )
            row["risk_note"] = (
                "Entry ATR history is incomplete; initialized from the first available post-entry ATR."
            )
        if row["current_trailing_stop"] is None:
            row["current_trailing_stop"] = row["entry_stop"]
        for i in after_entry:
            if i not in weekly_indices:
                continue
            if prior and bars[i]["as_of_date"] < prior["date"]:
                continue
            value = float(atr.iloc[i])
            if not isfinite(value) or value <= 0:
                continue
            candidate = max(
                Decimal(0), Decimal(str(bars[i]["close"])) - multiplier * Decimal(str(value))
            )
            row["current_trailing_stop"] = max(
                row["current_trailing_stop"] or Decimal(0), candidate
            )
            row["risk_date"] = bars[i]["as_of_date"]
            row["atr"] = Decimal(str(value))
            if prior:
                row["risk_basis"] = "persisted_atr_plus_weekly_close_ratchet"
        if row["atr"] is None and prior_entry:
            row["atr"] = Decimal(str(atr.iloc[prior_entry[-1]]))
            row["risk_date"] = row["risk_date"] or bars[prior_entry[-1]]["as_of_date"]
        result[instrument_id] = row
    return result
