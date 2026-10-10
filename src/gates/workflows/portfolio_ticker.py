"""Read-only portfolio valuation from account-scoped streaming quotes."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


def live_portfolio_ticker(ledger, market, quotes, stream, account_id):
    version = next(row["version"] for row in ledger.accounts() if row["account_id"] == account_id)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    projection = ledger.projection_at(account_id, today)
    positions = {}
    for lot in projection.open_lots:
        position = positions.setdefault(lot.instrument_id, {"units": 0, "cost": Decimal(0)})
        position["units"] += lot.remaining_units.units
        position["cost"] += lot.unit_cost.amount * lot.remaining_units.units
    holdings = []
    market_value, invested, day_pnl = Decimal(0), Decimal(0), Decimal(0)
    complete, day_complete, fresh_count = True, True, 0
    observed = []
    for instrument_id, position in positions.items():
        bars = market.bars(instrument_id, date.min, today, limit=1000)
        latest = bars[-1] if bars else None
        prior = next(
            (bar for bar in reversed(bars) if str(bar["as_of_date"]) < today.isoformat()), None
        )
        quote = quotes.read(account_id, instrument_id) if quotes else {"freshness": "MISSING"}
        fresh = quote["freshness"] == "FRESH"
        price = (
            Decimal(quote["price"]) if fresh else Decimal(str(latest["close"])) if latest else None
        )
        # Live day P&L needs the exchange's previous close for this quote.
        # An arbitrary older stored candle can represent several days' movement.
        previous = (
            Decimal(quote["previous_close"])
            if fresh and quote.get("previous_close") is not None
            else Decimal(str(prior["close"]))
            if not fresh and latest and str(latest["as_of_date"]) == today.isoformat() and prior
            else None
        )
        units, cost = position["units"], position["cost"]
        value = price * units if price is not None else None
        change = (price - previous) * units if price is not None and previous is not None else None
        complete = complete and value is not None
        day_complete = day_complete and change is not None
        market_value += value if value is not None else Decimal(0)
        invested += cost
        day_pnl += change if change is not None else Decimal(0)
        fresh_count += int(fresh)
        if fresh:
            observed.append(quote["observed_at"])
        identity = market.instrument_by_id(instrument_id)
        holdings.append(
            {
                "instrument_id": instrument_id,
                "symbol": identity["symbol"] if identity else None,
                "units": units,
                "cost": str(cost),
                "price": str(price) if price is not None else None,
                "previous_close": str(previous) if previous is not None else None,
                "market_value": str(value) if value is not None else None,
                "unrealised_pnl": str(value - cost) if value is not None else None,
                "day_pnl": str(change) if change is not None else None,
                "fresh": fresh,
                "freshness": quote["freshness"],
                "quote_time": quote.get("observed_at") if fresh else None,
                "price_date": quote["observed_at"][:10]
                if fresh
                else str(latest["as_of_date"])
                if latest
                else None,
                "price_basis": "kite-stream" if fresh else "market-bar",
            }
        )
    state = stream.state() if stream else {"status": "UNAVAILABLE", "enabled": False}
    return {
        "account_id": account_id,
        "ledger_version": version,
        "observed_on": today.isoformat(),
        "observed_at": max(observed) if observed else None,
        "cash": str(projection.cash.amount),
        "market_value": str(market_value) if complete else None,
        "equity": str(projection.cash.amount + market_value) if complete else None,
        "unrealised_pnl": str(market_value - invested) if complete else None,
        "day_pnl": str(day_pnl) if complete and day_complete else None,
        "realised_pnl": str(projection.realised_pnl.amount),
        "fresh_count": fresh_count,
        "holding_count": len(holdings),
        "all_quotes_fresh": bool(holdings) and fresh_count == len(holdings),
        "holdings": holdings,
        "basis": "account_scoped_live_quotes",
        "stream": {
            "status": state["status"],
            "enabled": bool(state.get("enabled")),
            "matches_account": state.get("account_id") == account_id,
        },
    }
