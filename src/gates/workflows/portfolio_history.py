"""Reconstruct portfolio curves from dated ledger history and observed prices."""

from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal

from src.gates.workflows.trading_calendar import TradingCalendar
from src.platform_kernel import DomainValidationError


def portfolio_history(ledger, market, account_id, as_of, limit=500, broker_snapshot=None):
    account = next((a for a in ledger.accounts() if a["account_id"] == account_id), None)
    if account is None:
        raise DomainValidationError("account not found")
    if not 1 <= limit <= 500:
        raise DomainValidationError("limit must be 1..500")
    opened = date.fromisoformat(account["opening_date"])
    if as_of < opened:
        return {
            "account_id": account_id,
            "basis": "ledger_and_historical_prices",
            "history": [],
            "missing_price_days": 0,
            "missing_symbols": [],
        }
    events = ledger.events(account_id)
    sessions = set(TradingCalendar(market.path).sessions(opened, as_of))
    dates = {opened, as_of, *sessions}
    instruments, transfers = set(), {}
    for event in events:
        day = date.fromisoformat(event["occurred_at"][:10])
        if opened <= day <= as_of:
            dates.add(day)
        payload = event["event"]
        if payload.get("instrument_id"):
            instruments.add(payload["instrument_id"])
        if event["event_type"] == "CASH_TRANSFER":
            transfers[day] = transfers.get(day, Decimal(0)) + Decimal(payload["amount"]) * (
                1 if payload["direction"] == "DEPOSIT" else -1
            )
    prices = {}
    for instrument_id in instruments:
        bars, through = [], as_of
        while through >= opened:
            batch = market.bars(instrument_id, opened, through, limit=1000)
            bars = batch + bars
            if len(batch) < 1000:
                break
            through = date.fromisoformat(batch[0]["as_of_date"]) - timedelta(days=1)
        prices[instrument_id] = (
            [bar["as_of_date"] for bar in bars],
            [Decimal(str(bar["close"])) for bar in bars],
        )
    current_prices = {
        row["instrument_id"]: Decimal(row["price"])
        for row in (broker_snapshot or {}).get("holdings", [])
    }
    broker_day = (broker_snapshot or {}).get("observed_at", "")[:10]
    history, missing, skipped = [], set(), 0
    # Use a consistent priced subset across the entire curve. Excluding only
    # market value would incorrectly turn unpriced purchases into total losses.
    projections = {day: ledger.projection_at(account_id, day) for day in sorted(dates)}
    for day, projection in projections.items():
        unavailable = set()
        for lot in projection.open_lots:
            if day == as_of and broker_day == day.isoformat() and lot.instrument_id in current_prices:
                continue
            price_dates, _ = prices.get(lot.instrument_id, ([], []))
            position = bisect_right(price_dates, day.isoformat()) - 1
            if position < 0 or (day in sessions and day != as_of and price_dates[position] != day.isoformat()):
                unavailable.add(lot.instrument_id)
        if unavailable:
            skipped += 1
            missing.update(unavailable)
    prior_equity, prior_day, index, peak = None, None, Decimal(1), Decimal(1)
    for day in sorted(dates):
        projection = ledger.projection_at(account_id, day, excluded_instrument_ids=missing) if missing else projections[day]
        equity, stale, complete = projection.cash.amount, 0, True
        for lot in projection.open_lots:
            if (
                day == as_of
                and broker_day == day.isoformat()
                and lot.instrument_id in current_prices
            ):
                price = current_prices[lot.instrument_id]
            else:
                price_dates, closes = prices.get(lot.instrument_id, ([], []))
                position = bisect_right(price_dates, day.isoformat()) - 1
                if position < 0:
                    missing.add(lot.instrument_id)
                    complete = False
                    continue
                price = closes[position]
                stale += price_dates[position] != day.isoformat()
            equity += price * lot.remaining_units.units
        if not complete:
            skipped += 1
            continue
        if prior_equity is not None:
            flow = sum(
                (
                    amount
                    for transfer_day, amount in transfers.items()
                    if prior_day < transfer_day <= day
                ),
                Decimal(0),
            )
            capital = prior_equity + flow
            if capital > 0:
                index *= equity / capital
        peak = max(peak, index)
        history.append(
            {
                "as_of_date": day.isoformat(),
                "equity": str(equity),
                "drawdown": str(index / peak - 1) if peak > 0 else "0",
                "return_index": str(index),
                "stale_prices": stale,
            }
        )
        prior_equity, prior_day = equity, day
    missing_symbols = []
    for instrument_id in sorted(missing):
        identity = market.instrument_by_id(instrument_id)
        missing_symbols.append(identity["symbol"] if identity else instrument_id)
    return {
        "account_id": account_id,
        "basis": "ledger_and_historical_prices",
        "drawdown_basis": "cash_flow_adjusted_priced_subset" if missing else "cash_flow_adjusted_available_valuations",
        "partial": bool(missing),
        "excluded_symbols": missing_symbols,
        "history": history[-limit:],
        "missing_price_days": skipped,
        "missing_symbols": missing_symbols,
    }
