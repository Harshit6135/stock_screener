"""Read-only portfolio valuation from recorded ledger, price and risk inputs."""

import json
from datetime import date
from decimal import Decimal

from src.domains.portfolio_accounting import PortfolioPerformance
from src.domains.portfolio_accounting.portfolio_performance import (
    calculate_open_holdings_xirr,
    calculate_xirr,
)
from src.domains.portfolio_accounting.portfolio_tax import portfolio_tax_estimates
from src.gates.workflows.portfolio_stops import latest_saved_stops, portfolio_stops


def portfolio_valuation(
    ledger, market, account_id, as_of, risk_reader=None, broker_sync=None, *, broker_snapshot=None
):
    projection = ledger.projection_at(account_id, as_of)
    account_events = ledger.events(account_id)
    instruments = {lot.instrument_id for lot in projection.open_lots}
    bars_by_instrument = {
        instrument_id: market.bars(instrument_id, date.min, as_of, limit=1000)
        for instrument_id in instruments
    }
    identities = {
        instrument_id: market.instrument_by_id(instrument_id) for instrument_id in instruments
    }
    holdings = []
    market_value = Decimal(0)
    invested = Decimal(0)
    stop_risk = Decimal(0)
    capital_risk = Decimal(0)
    portfolio_risk = Decimal(0)
    capital_risk_complete = True
    risk_complete = True
    saved_stops = latest_saved_stops(risk_reader(account_id) if risk_reader else [], as_of)
    calculated_stops = portfolio_stops(market, projection.open_lots, as_of, saved_stops)
    if broker_sync:
        broker_snapshot = broker_sync.holding_snapshot(account_id)
    broker_rows = (
        {row["instrument_id"]: row for row in broker_snapshot["holdings"]}
        if broker_snapshot
        else {}
    )
    broker_date = broker_snapshot["observed_at"][:10] if broker_snapshot else None
    dated_ids = {
        event["event"]["instrument_id"]
        for event in account_events
        if event["event_type"] == "OPEN_LOTS_RECONCILED"
        and event["occurred_at"][:10] <= as_of.isoformat()
    }
    for lot in projection.open_lots:
        bars = bars_by_instrument[lot.instrument_id]
        latest = bars[-1] if bars else None
        broker_row = broker_rows.get(lot.instrument_id)
        broker_price = bool(broker_row and broker_date == as_of.isoformat())
        if broker_price:
            latest = {"close": broker_row["price"], "as_of_date": broker_date}
        value = Decimal(str(latest["close"])) * lot.remaining_units.units if latest else Decimal(0)
        cost = lot.unit_cost.amount * lot.remaining_units.units
        stop_info = calculated_stops.get(lot.instrument_id, {})
        current_stop = stop_info.get("current_trailing_stop")
        if current_stop is not None:
            lot_capital_risk = cost - current_stop * lot.remaining_units.units
            capital_risk += lot_capital_risk
            portfolio_risk += max(Decimal(0), lot_capital_risk)
        else:
            capital_risk_complete = False
        hard_stop = current_stop * Decimal("0.97") if current_stop is not None else None
        current_price = Decimal(str(latest["close"])) if latest else None
        previous_bar = next(
            (bar for bar in reversed(bars) if str(bar["as_of_date"]) < as_of.isoformat()), None
        )
        previous_close = Decimal(str(previous_bar["close"])) if previous_bar else None
        holding_day_pnl = (
            (current_price - previous_close) * lot.remaining_units.units
            if current_price is not None
            and previous_close is not None
            and str(latest["as_of_date"]) == as_of.isoformat()
            else None
        )
        stop_status = (
            "unavailable"
            if current_stop is None or current_price is None
            else "below_hard_stop"
            if current_price <= hard_stop
            else "below_trailing_stop"
            if current_price <= current_stop
            else "above_stop"
        )
        lot_risk = (
            max(Decimal(0), value - current_stop * lot.remaining_units.units)
            if current_stop is not None and current_price is not None
            else None
        )
        if lot_risk is not None:
            stop_risk += lot_risk
        else:
            risk_complete = False
        market_value += value
        invested += cost
        identity = identities[lot.instrument_id]
        holdings.append(
            {
                "instrument_id": lot.instrument_id,
                "acquisition_date": lot.opened_on.isoformat(),
                "purchase_date_known": True
                if lot.instrument_id in dated_ids
                else broker_row.get("purchase_date_known", True)
                if broker_row
                else True,
                "price_basis": "kite-portfolio-snapshot" if broker_price else "market-bar",
                "symbol": identity["symbol"] if identity else None,
                "units": lot.remaining_units.units,
                "cost": str(cost),
                "previous_close": str(previous_close) if previous_close is not None else None,
                "day_pnl": str(holding_day_pnl) if holding_day_pnl is not None else None,
                "price": str(latest["close"]) if latest else None,
                "price_date": latest["as_of_date"] if latest else None,
                "fresh": bool(latest and latest["as_of_date"] == as_of.isoformat()),
                "market_value": str(value),
                "entry_stop": str(stop_info["entry_stop"])
                if stop_info.get("entry_stop") is not None
                else None,
                "atr": str(stop_info["atr"]) if stop_info.get("atr") is not None else None,
                "risk_date": stop_info.get("risk_date"),
                "risk_basis": stop_info.get("risk_basis"),
                "risk_note": stop_info.get("risk_note"),
                "stop_status": stop_status,
                "current_trailing_stop": str(current_stop) if current_stop is not None else None,
                "hard_stop": str(hard_stop) if hard_stop is not None else None,
                "stop_risk": str(lot_risk) if lot_risk is not None else None,
                "capital_risk": str(cost - current_stop * lot.remaining_units.units)
                if current_stop is not None
                else None,
            }
        )
    # Display one position per instrument and acquisition day. Keep the
    # original execution lots in the ledger for FIFO sale accounting.
    grouped_holdings = {}
    for holding in holdings:
        key = (holding["instrument_id"], holding["acquisition_date"])
        if key not in grouped_holdings:
            grouped_holdings[key] = dict(holding)
            continue
        combined = grouped_holdings[key]
        combined["units"] += holding["units"]
        for field in ("cost", "market_value", "stop_risk", "day_pnl", "capital_risk"):
            combined[field] = (
                str(Decimal(combined[field]) + Decimal(holding[field]))
                if combined[field] is not None and holding[field] is not None
                else None
            )
        combined["purchase_date_known"] = (
            combined["purchase_date_known"] and holding["purchase_date_known"]
        )
    holdings = list(grouped_holdings.values())
    portfolio_risk = sum(
        (
            max(Decimal(0), Decimal(h["capital_risk"]))
            for h in holdings
            if h["capital_risk"] is not None
        ),
        Decimal(0),
    )
    # Only investor capital and original imported cost belong in the return
    # cash-flow basis.  Normal buys/sells are internal transfers and must
    # not be counted again as contributions or withdrawals.
    prices_complete = all(holding["price"] is not None for holding in holdings)
    xirr = (
        PortfolioPerformance(ledger).calculate_xirr(
            account_id, projection.cash.amount + market_value, as_of
        )
        if prices_complete
        else None
    )
    holdings_xirr = calculate_open_holdings_xirr(holdings, as_of)
    account = next(row for row in ledger.accounts() if row["account_id"] == account_id)
    events = [event for event in account_events if event["occurred_at"][:10] <= as_of.isoformat()]
    history_incomplete = False
    funded_versions = {
        version
        for event in events
        if event["event_type"] == "IMPORTED_POSITION_FUNDED"
        for version in event["event"]["import_versions"]
    }
    return_basis_incomplete = False
    for event in events:
        if event["event_type"] != "OPENING_POSITION_IMPORTED":
            continue
        try:
            provenance = json.loads(str(event["event"].get("broker_provenance", "{}")))
        except ValueError:
            continue
        if isinstance(provenance, dict) and provenance.get("history_incomplete"):
            history_incomplete = True
            # An additional purchase funded from this account is an internal
            # cash-to-stock transfer, not a new external contribution.
            # Snapshot-only imports without a dated funding basis remain
            # unsuitable for whole-account annualization.
            return_basis_incomplete |= not (
                event["version"] in funded_versions
                and provenance.get("purchase_date_known") is True
                and account["opening_date"]
                <= event["event"].get("acquisition_date", "")
                <= as_of.isoformat()
            )
    if return_basis_incomplete:
        xirr = None
    transfers = [event for event in events if event["event_type"] == "CASH_TRANSFER"]
    net_capital = Decimal(account["opening_cash"]) + sum(
        (
            Decimal(e["event"]["amount"]) * (1 if e["event"]["direction"] == "DEPOSIT" else -1)
            for e in transfers
        ),
        Decimal(0),
    )
    equity = projection.cash.amount + market_value
    realised_flows = []
    closed_trades = ledger.journal(account_id, as_of=as_of)
    for trade in closed_trades:
        if trade["sell_date"] > as_of.isoformat():
            continue
        buy_value = Decimal(trade["buy_price"]) * trade["units"]
        # Journal buy cost includes allocated buy fees; realised P&L also
        # subtracts allocated sell fees. Derive actual net sale proceeds.
        realised_flows.extend(
            [
                (date.fromisoformat(trade["buy_date"]), -buy_value),
                (
                    date.fromisoformat(trade["sell_date"]),
                    buy_value + Decimal(trade["realised_pnl"]),
                ),
            ]
        )
    realised_xirr = calculate_xirr(realised_flows)
    effective_events = [
        e for e in ledger.effective_events(account_id) if e["occurred_at"][:10] <= as_of.isoformat()
    ]
    recorded_charges = sum(
        (
            Decimal(event["event"].get("fee", "0"))
            for event in effective_events
            if event["event_type"] == "FILL_RECORDED"
        ),
        Decimal(0),
    )
    recorded_charges += sum(
        (
            sum((Decimal(c["amount"]) for c in e["charge_components"]), Decimal(0))
            for e in effective_events
            if e["event_type"] == "OPENING_POSITION_IMPORTED"
        ),
        Decimal(0),
    )
    net_gain = equity - net_capital
    elapsed = (as_of - date.fromisoformat(account["opening_date"])).days
    annualized = (
        (equity / Decimal(account["opening_cash"])) ** (Decimal(365) / elapsed) - 1
        if elapsed > 0
        and Decimal(account["opening_cash"]) > 0
        and equity > 0
        and not transfers
        and prices_complete
        and not return_basis_incomplete
        else None
    )
    day_pnl = None
    day_pnl_basis = "prior_session_valuation_unavailable"
    from datetime import timedelta

    from src.gates.workflows.trading_calendar import TradingCalendar

    prior_sessions = TradingCalendar(market.path).sessions(
        as_of - timedelta(days=14), as_of - timedelta(days=1)
    )
    prior_date = prior_sessions[-1] if prior_sessions else None
    snapshots = ledger.valuations(account_id, 100)
    previous = next(
        (row for row in snapshots if prior_date and row["as_of_date"] == prior_date.isoformat()),
        None,
    )
    if previous:
        flows = Decimal(0)
        imports = False
        for event in account_events:
            event_day = date.fromisoformat(event["occurred_at"][:10])
            if prior_date < event_day <= as_of:
                if event["event_type"] == "CASH_TRANSFER":
                    flow = event["event"]
                    flows += Decimal(flow["amount"]) * (1 if flow["direction"] == "DEPOSIT" else -1)
                elif event["event_type"] == "OPENING_POSITION_IMPORTED":
                    imports = True
        if not imports:
            day_pnl = (
                projection.cash.amount
                + market_value
                - Decimal(previous["payload"]["equity"])
                - flows
            )
            day_pnl_basis = "prior_session_valuation_less_external_capital"
        else:
            day_pnl_basis = "opening_import_requires_prior_session_basis"
    result = {
        "account_id": account_id,
        "as_of_date": as_of.isoformat(),
        "cash": str(projection.cash.amount),
        "invested_cost": str(invested),
        "market_value": str(market_value),
        "unrealised_gain": str(market_value - invested) if prices_complete else None,
        "equity": str(projection.cash.amount + market_value),
        "realised_pnl": str(projection.realised_pnl.amount),
        "stop_based_risk": str(stop_risk) if risk_complete else None,
        "capital_risk": str(capital_risk) if capital_risk_complete else None,
        "portfolio_risk": str(portfolio_risk) if capital_risk_complete else None,
        "tax_estimates": portfolio_tax_estimates(closed_trades, as_of),
        "recorded_charges": str(recorded_charges),
        "realised_xirr": str(realised_xirr) if realised_xirr is not None else None,
        "stop_risk_fraction": str(stop_risk / equity) if risk_complete and equity > 0 else None,
        "breached_stop_holdings": len(
            {
                h["instrument_id"]
                for h in holdings
                if h["stop_status"] in {"below_trailing_stop", "below_hard_stop"}
            }
        ),
        "xirr": str(xirr) if xirr is not None else None,
        "holdings_xirr": str(holdings_xirr) if holdings_xirr is not None else None,
        "annualized_return": str(annualized) if annualized is not None else None,
        "net_gain": str(net_gain) if prices_complete else None,
        "net_contributed_capital": str(net_capital),
        "total_return": str(net_gain / net_capital)
        if net_capital > 0 and prices_complete
        else None,
        "opening_date": account["opening_date"],
        "initial_balance": account["opening_cash"],
        "fees_note": "Some imported trades have no charges data; their gains exclude brokerage and taxes."
        if any(
            e["event_type"] == "FILL_RECORDED"
            and e["event"].get("correlation_id") == "tradebook:charges-unavailable"
            and not any(c["charge_group"] == "contract" for c in e["charge_components"])
            for e in effective_events
        )
        else None,
        "history_complete": not history_incomplete,
        "return_basis": "recorded_capital_and_cash_funded_purchases"
        if history_incomplete and not return_basis_incomplete
        else "incomplete_import_history"
        if return_basis_incomplete
        else "recorded_history",
        "performance_note": "Direct Kite imports include current balances and purchase dates, but no prior sells. Realized gains and curves use recorded transactions only; whole-account XIRR and annualized return require complete trade history."
        if history_incomplete
        else None,
        "day_pnl": str(day_pnl) if day_pnl is not None else None,
        "day_pnl_basis": day_pnl_basis,
        "stale_prices": sum(not item["fresh"] for item in holdings),
        "holdings": holdings,
    }
    return result
