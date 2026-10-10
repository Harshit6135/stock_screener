"""Reviewable stop exits and approval-scoped Kite execution."""

import logging
import threading
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from kiteconnect.exceptions import KiteException
from requests.exceptions import RequestException

from src.domains.execution import KiteExecutionGateway
from src.gates.workflows.broker_orders import BrokerOrderWorkflow
from src.gates.workflows.portfolio_stops import (
    completed_week_end,
    latest_saved_stops,
    portfolio_stops,
)
from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection


def india_now():
    return datetime.now(ZoneInfo("Asia/Kolkata"))


class ApprovedStopGateway(KiteExecutionGateway):
    """Arm only the exact stop sell approved by the operator in this request."""

    def __init__(self, workflow, proposal):
        self.workflow, self.proposal = workflow, proposal
        self.decision = proposal["decisions"][0]
        super().__init__(
            None,
            ".",
            enabled=True,
            accounts=workflow.accounts,
            allowed_accounts=[proposal["account_id"]],
            allowed_instruments=[self.decision["instrument_id"]],
        )
        self.arm()

    def _client(self, account_id=None, *, for_write=True):
        if account_id != self.proposal["account_id"]:
            raise DomainValidationError("stop order account does not match approval")
        broker_account = self.workflow.broker_account(account_id)
        self.accounts.validate(broker_account)
        return self.accounts.client(broker_account)

    def submit_order(self, order):
        if self.workflow.store.get(self.proposal["proposal_id"])["status"] != "APPROVED":
            raise DomainValidationError("stop sell requires recorded approval")
        if (
            order["proposal_id"] != self.proposal["proposal_id"]
            or order["side"] != "SELL"
            or order["instrument_id"] != self.decision["instrument_id"]
            or int(order["quantity"]) != self.decision["units"]
        ):
            raise DomainValidationError("order does not match the approved stop sell")
        self.workflow.validate_execution(self.proposal)
        client = self._client(str(order["account_id"]))
        return str(
            client.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=str(order["symbol"]),
                transaction_type="SELL",
                quantity=int(order["quantity"]),
                order_type="MARKET",
                product="CNC",
                validity="DAY",
                tag=self._order_tag(order),
                market_protection=-1,
            )
        )


class StopSellWorkflow:
    STRATEGY = "portfolio_stop"

    def __init__(self, actions, orders, accounts):
        self.actions, self.orders, self.accounts = actions, orders, accounts
        self.ledger, self.market = actions.ledger, actions.market
        self.store = actions.proposals_store

    def broker_account(self, account_id):
        try:
            return self.accounts.binding(account_id)["broker_account_id"]
        except DomainValidationError:
            # Accounts created on Home explicitly share their broker/ledger ID.
            self.accounts.get_credentials(account_id)
            return account_id

    def saved_stops(self, account_id, today):
        return latest_saved_stops(self.actions.risk_projection(account_id), today)

    def uncommitted_shares(self, client, instrument_id, symbol):
        instrument = self.market.instrument_by_id(instrument_id)
        isin = instrument.get("isin") if instrument else None
        aliases = {("NSE", symbol)}
        available = 0
        for row in client.holdings():
            if row.get("product", "CNC") != "CNC":
                continue
            # Demat holdings are exchange independent. BSE symbols may differ,
            # so only a matching ISIN can establish that cross-exchange identity.
            matches = (
                row["isin"] == isin
                if row.get("isin") and isin
                else row.get("exchange") == "NSE" and row.get("tradingsymbol") == symbol
            )
            if not matches:
                continue
            aliases.add((row.get("exchange"), row.get("tradingsymbol")))
            available += int(row.get("quantity", 0)) + int(row.get("t1_quantity", 0))
        for row in client.positions().get("net", []):
            identity = (row.get("exchange"), row.get("tradingsymbol"))
            if identity in aliases and row.get("product") == "CNC":
                quantity = int(row.get("quantity", 0))
                # Same-day BSE purchases cannot fund an NSE sell. Executed
                # delivery sells on either exchange do reduce availability.
                if identity == ("NSE", symbol) or quantity < 0:
                    available += quantity
        outstanding = sum(
            max(0, int(row.get("quantity", 0)) - int(row.get("filled_quantity", 0)))
            for row in client.orders()
            if (row.get("exchange"), row.get("tradingsymbol")) in aliases
            and row.get("product", "CNC") == "CNC"
            and row.get("transaction_type") == "SELL"
            and row.get("status") not in {"COMPLETE", "CANCELLED", "REJECTED"}
        )
        return available - outstanding

    def live_price(self, client, symbol):
        key = "NSE:" + symbol
        try:
            row = client.quote([key]).get(key)
        except (KiteException, RequestException) as exc:
            raise DomainValidationError(
                "Kite live quote request failed; reconnect and retry"
            ) from exc
        if not row:
            raise DomainValidationError("live Kite quote is unavailable")
        stamp = row.get("timestamp")
        if not stamp:
            raise DomainValidationError("live Kite quote has no timestamp")
        try:
            stamp = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            age = (india_now() - stamp).total_seconds()
            price = Decimal(str(row["last_price"]))
        except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
            raise DomainValidationError("Kite quote timestamp or price is invalid") from exc
        if not -5 <= age <= 120 or not price.is_finite() or price <= 0:
            raise DomainValidationError(
                "live Kite quote is stale or invalid; refresh during market hours"
            )
        return price

    def check(self, account_id):
        account = next(
            (row for row in self.ledger.accounts() if row["account_id"] == account_id), None
        )
        if account is None:
            raise DomainValidationError("portfolio account does not exist")
        now = india_now()
        today = now.date()
        lots = self.ledger.projection(account_id).open_lots
        stops = portfolio_stops(self.market, lots, today, self.saved_stops(account_id, today))
        quantities = {}
        for lot in lots:
            quantities[lot.instrument_id] = (
                quantities.get(lot.instrument_id, 0) + lot.remaining_units.units
            )
        with sqlite_connection(self.orders.database, read_only=True) as connection:
            rows = connection.execute(
                "SELECT proposal_id FROM action_proposals WHERE account_id=? AND strategy_id=? AND status IN ('PENDING','APPROVED')",
                (account_id, self.STRATEGY),
            ).fetchall()
        created, checks = [], []
        for row in rows:
            prior = self.store.get(row[0])
            weekly = prior["decisions"][0].get("stop_schedule") == "weekly"
            if (
                (
                    not weekly
                    and (prior["action_date"] != today.isoformat() or now.time() >= time(15, 30))
                )
                or prior["decisions"][0].get("stop_schedule") not in {"weekly", "intraday"}
                or prior["expected_ledger_version"] != account["version"]
                or prior["decisions"][0].get("account_details_version", 0)
                != account.get("details_version", 0)
            ) and self.store.expire_unsubmitted_stop(row[0], datetime.now(UTC).isoformat()):
                if self.actions.risk_guard:
                    self.actions.risk_guard.release(f"proposal:{row[0]}")
                    self.actions.risk_guard.release(f"proposal:{row[0]}:stock:0")
                continue
            created.append(prior)
        client = None
        week_end = completed_week_end(today)
        weekly_sessions = self.market.session_dates(
            week_end - timedelta(days=4), week_end, exchange="NSE"
        )
        if quantities and now.weekday() < 5 and time(9, 15) <= now.time() < time(15, 30):
            try:
                broker_account = self.broker_account(account_id)
                self.accounts.validate(broker_account)
                client = self.accounts.client(broker_account)
            except DomainValidationError:
                pass
        for instrument_id, units in quantities.items():
            if any(row["decisions"][0]["instrument_id"] == instrument_id for row in created):
                existing = next(
                    row for row in created if row["decisions"][0]["instrument_id"] == instrument_id
                )
                decision = existing["decisions"][0]
                checks.append(
                    {
                        "instrument_id": instrument_id,
                        "symbol": decision["symbol"],
                        "status": "review_exists",
                        "price": decision["execution_price"],
                        "stop_threshold": decision["hard_stop"]
                        if decision["type"] == "HARD_STOP"
                        else decision["stop_threshold"],
                        "stop_schedule": decision.get("stop_schedule", "legacy"),
                        "price_source": decision["price_source"],
                        "price_date": decision["price_date"],
                    }
                )
                continue
            stop = stops[instrument_id]
            threshold = stop["current_trailing_stop"]
            identity = self.market.instrument_by_id(instrument_id)
            if threshold is None or threshold <= 0:
                checks.append(
                    {
                        "instrument_id": instrument_id,
                        "symbol": identity["symbol"] if identity else instrument_id,
                        "status": "stop_unavailable",
                        "reason": stop.get("risk_note")
                        or "Completed OHLC history is needed to calculate a stop",
                    }
                )
                continue
            bars = self.market.bars(instrument_id, date.min, today, limit=1)
            if not identity or identity["exchange"] != "NSE" or not bars:
                continue
            price, price_date, source = (
                Decimal(str(bars[-1]["close"])),
                bars[-1]["as_of_date"],
                "stored_close",
            )
            if client:
                try:
                    price = self.live_price(client, identity["symbol"])
                    price_date, source = today.isoformat(), "live_kite"
                except DomainValidationError:
                    # A historical close can produce a review action, never a live execution.
                    source = "stored_close"
            hard = threshold * Decimal("0.97")
            # Live ticks only trigger the hard stop. A normal stop is a frozen
            # decision from a completed weekly close, independent of live price.
            hard_breached = source == "live_kite" and price <= hard
            weekly_price, weekly_date = stop["weekly_close"], stop["weekly_close_date"]
            weekly_breached = (
                weekly_price is not None
                and weekly_price < threshold
                and weekly_sessions
                and weekly_date == weekly_sessions[-1]
                and (completed_week_end(today) - date.fromisoformat(weekly_date)).days <= 4
                and any(
                    lot.instrument_id == instrument_id
                    and lot.opened_on <= date.fromisoformat(weekly_date)
                    for lot in lots
                )
            )
            if weekly_breached and not hard_breached:
                price, price_date, source = weekly_price, weekly_date, "weekly_close"
            checks.append(
                {
                    "instrument_id": instrument_id,
                    "symbol": identity["symbol"],
                    "status": "breached"
                    if hard_breached or weekly_breached
                    else "live_unavailable"
                    if source == "stored_close"
                    else "above_stop",
                    "price": str(price),
                    "stop_threshold": str(threshold if source == "weekly_close" else hard),
                    "stop_schedule": "weekly" if source == "weekly_close" else "intraday",
                    "price_source": source,
                    "price_date": price_date,
                }
            )
            if not hard_breached and not weekly_breached:
                continue
            schedule = "intraday" if hard_breached else "weekly"
            action_date = today
            if not hard_breached:
                price, price_date, source = weekly_price, weekly_date, "weekly_close"
                action_date = date.fromisoformat(weekly_date) + timedelta(days=1)
                while action_date.weekday() != 0:
                    action_date += timedelta(days=1)
            proposal_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"stop-sell:{account_id}:{instrument_id}:{account['version']}:{account.get('details_version', 0)}:{schedule}:{price_date}",
                )
            )
            try:
                existing = self.store.get(proposal_id)
                created.append(existing)
                continue
            except DomainValidationError:
                pass
            decision = {
                "type": "HARD_STOP" if hard_breached else "STOP_LOSS",
                "stop_schedule": schedule,
                "instrument_id": instrument_id,
                "symbol": identity["symbol"],
                "units": units,
                "execution_price": str(price),
                "fee": "0",
                "protective": True,
                "stop_threshold": str(threshold),
                "hard_stop": str(hard),
                "risk_date": stop["risk_date"],
                "price_date": price_date,
                "price_source": source,
                "account_details_version": account.get("details_version", 0),
                "reason": (
                    f"Sell {units} shares: live price {price} breached hard stop {hard:.2f}. Hard stop rechecked on approval."
                    if hard_breached
                    else f"Sell {units} shares next week: {price_date} weekly close {price} was below trailing stop {threshold:.2f}. Price recovery does not cancel this weekly sell."
                ),
            }
            timestamp = datetime.now(UTC).isoformat()
            self.store.recover_pending(
                proposal_id=proposal_id,
                account_id=account_id,
                strategy_id=self.STRATEGY,
                action_date=action_date.isoformat(),
                ranking_week_end=price_date,
                expected_ledger_version=account["version"],
                artifact_id=proposal_id,
                decisions=[decision],
                timestamp=timestamp,
                event_type="STOP_BREACHED",
            )
            created.append(self.store.get(proposal_id))
        return {
            "proposals": [self.readback(row) for row in created],
            "checks": checks,
            "submitted": False,
        }

    def readback(self, proposal):
        if proposal["strategy_id"] != self.STRATEGY:
            return proposal
        with sqlite_connection(self.orders.database, read_only=True) as connection:
            row = connection.execute(
                "SELECT order_id FROM broker_orders WHERE proposal_id=?", (proposal["proposal_id"],)
            ).fetchone()
        return {**proposal, "broker_order": self.orders.get(row[0]) if row else None}

    def validate_execution(self, proposal):
        current = self.store.get(proposal["proposal_id"])
        if current["strategy_id"] != self.STRATEGY or len(current["decisions"]) != 1:
            raise DomainValidationError("only a generated stop sell can use this execution route")
        decision = current["decisions"][0]
        if decision["type"] not in {"STOP_LOSS", "HARD_STOP"}:
            raise DomainValidationError("stop execution requires a protective sell")
        if decision.get("stop_schedule") not in {"weekly", "intraday"}:
            raise DomainValidationError("stop schedule changed; check stops again before selling")
        now = india_now()
        weekly = decision.get("stop_schedule") == "weekly" and decision["type"] == "STOP_LOSS"
        if weekly and date.fromisoformat(current["action_date"]) > now.date():
            raise DomainValidationError("weekly stop sell is due at the next week's market open")
        if not weekly and current["action_date"] != now.date().isoformat():
            raise DomainValidationError("stop action is from a previous day; check stops again")
        if decision["type"] == "STOP_LOSS" and not weekly:
            raise DomainValidationError(
                "normal stops require a completed weekly close; check stops again"
            )
        if now.weekday() >= 5 or not time(9, 15) <= now.time() < time(15, 30):
            raise DomainValidationError(
                "approve stop sells during NSE market hours (09:15–15:30 IST)"
            )
        account = next(
            row for row in self.ledger.accounts() if row["account_id"] == current["account_id"]
        )
        if account["version"] != current["expected_ledger_version"] or account.get(
            "details_version", 0
        ) != decision.get("account_details_version", 0):
            raise DomainValidationError("portfolio changed since this action; check stops again")
        held = sum(
            lot.remaining_units.units
            for lot in self.ledger.projection(current["account_id"]).open_lots
            if lot.instrument_id == decision["instrument_id"]
        )
        if held != decision["units"]:
            raise DomainValidationError("held quantity changed since this sell action")
        stops = portfolio_stops(
            self.market,
            self.ledger.projection(current["account_id"]).open_lots,
            now.date(),
            self.saved_stops(current["account_id"], now.date()),
        )
        stop = stops[decision["instrument_id"]]
        sessions = self.market.session_dates(
            now.date() - timedelta(days=21), completed_week_end(now.date()), exchange="NSE"
        )
        if (
            not sessions
            or not stop["risk_date"]
            or stop["risk_date"] < sessions[-1]
            or (now.date() - date.fromisoformat(stop["risk_date"])).days > 10
        ):
            raise DomainValidationError(
                "stop OHLC history is stale; refresh market data before selling"
            )
        broker_account = self.broker_account(current["account_id"])
        self.accounts.validate(broker_account)
        client = self.accounts.client(broker_account)
        price = self.live_price(client, decision["symbol"])
        if not weekly and price > Decimal(decision["hard_stop"]):
            raise DomainValidationError(
                "live price recovered above the approved hard stop; no sell submitted"
            )
        if (
            self.uncommitted_shares(client, decision["instrument_id"], decision["symbol"])
            < decision["units"]
        ):
            raise DomainValidationError("Kite has fewer uncommitted shares than this sell action")
        return current

    def broker_workflow(self, proposal):
        workflow = BrokerOrderWorkflow(
            self.orders.database,
            self.ledger,
            ApprovedStopGateway(self, proposal),
            repository=self.orders.repository,
            proposal_store=self.store,
            market=self.market,
        )
        workflow.risk_guard = self.orders.risk_guard
        return workflow

    def approve_and_execute(self, proposal_id):
        proposal = self.store.get(proposal_id)
        if proposal["strategy_id"] != self.STRATEGY:
            raise DomainValidationError("only stop actions support approve and sell")
        if proposal["status"] not in {"PENDING", "APPROVED", "PROCESSED"}:
            raise DomainValidationError("stop action was rejected")
        with sqlite_connection(self.orders.database, read_only=True) as connection:
            existing = connection.execute(
                "SELECT order_id FROM broker_orders WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        if existing:
            order = self.orders.get(existing[0])
            if order["status"] != "LOCAL_CREATED":
                return {"proposal": proposal, "order": order}
        self.validate_execution(proposal)
        if proposal["status"] == "PENDING":
            proposal = self.actions.decide(proposal_id, "APPROVED")
        decision = proposal["decisions"][0]
        order = self.orders.create_intent(
            {
                "account_id": proposal["account_id"],
                "proposal_id": proposal_id,
                "idempotency_key": f"stop-sell:{proposal_id}",
                "instrument_id": decision["instrument_id"],
                "symbol": decision["symbol"],
                "exchange": "NSE",
                "side": "SELL",
                "quantity": decision["units"],
                "order_type": "MARKET",
                "variety": "regular",
                "broker_account_id": self.broker_account(proposal["account_id"]),
                "strategy_id": self.STRATEGY,
                "exit_reason": "hard_stop" if decision["type"] == "HARD_STOP" else "strategy_stop",
                "expected_ledger_version": proposal["expected_ledger_version"],
            }
        )
        order = self.broker_workflow(proposal).submit(order["order_id"])
        return {"proposal": self.store.get(proposal_id), "order": order}

    def reconcile(self, proposal_id):
        proposal = self.store.get(proposal_id)
        if proposal["strategy_id"] != self.STRATEGY:
            raise DomainValidationError("only stop actions support this order refresh")
        with sqlite_connection(self.orders.database, read_only=True) as connection:
            row = connection.execute(
                "SELECT order_id FROM broker_orders WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        if not row:
            raise DomainValidationError("this action has no submitted order")
        workflow = self.broker_workflow(proposal)
        order = workflow.get(row[0])
        missing_fills = (
            order["status"] == "FILLED"
            and workflow.repository.fill_quantity(row[0]) < order["quantity"]
        )
        if missing_fills or order["status"] not in {
            "FILLED",
            "CANCELLED",
            "REJECTED",
            "LOCAL_CREATED",
        }:
            order = workflow.reconcile(row[0])
        if order["status"] == "FILLED":
            version = next(
                row["version"]
                for row in self.ledger.accounts()
                if row["account_id"] == proposal["account_id"]
            )
            with sqlite_connection(self.orders.database) as connection:
                self.store.mark_processed(
                    connection, proposal_id, version, datetime.now(UTC).isoformat(), []
                )
        return {"proposal": self.store.get(proposal_id), "order": order}


class BackgroundStopMonitor:
    """Detect stops and reconcile fills; execute only explicit strategy requests."""

    def __init__(self, workflow, interval_seconds=30, proposal_execution=None):
        self.workflow, self.interval_seconds = workflow, interval_seconds
        self.proposal_execution = proposal_execution
        self._stop = threading.Event()
        self._thread = None

    def tick(self):
        for account in self.workflow.ledger.accounts():
            self.workflow.check(account["account_id"])
        with sqlite_connection(self.workflow.orders.database, read_only=True) as connection:
            rows = connection.execute("""SELECT DISTINCT p.proposal_id FROM action_proposals p
                JOIN broker_orders o ON o.proposal_id=p.proposal_id
                WHERE p.strategy_id='portfolio_stop' AND o.status IN
                ('SUBMITTED','PARTIALLY_FILLED','SUBMITTING','SUBMIT_UNKNOWN','FILLED')""").fetchall()
        for row in rows:
            proposal = self.workflow.store.get(row[0])
            order = self.workflow.readback(proposal)["broker_order"]
            if order["status"] == "FILLED" and (
                not order["broker_order_id"]
                or self.workflow.orders.repository.fill_quantity(order["order_id"])
                >= order["quantity"]
            ):
                continue
            try:
                self.workflow.reconcile(row[0])
            except DomainValidationError as exc:
                logging.getLogger(__name__).warning("Stop order reconciliation pending: %s", exc)
        if self.proposal_execution:
            self.proposal_execution.tick()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="portfolio-stop-monitor", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logging.getLogger(__name__).exception("Portfolio stop monitor failed")
            self._stop.wait(self.interval_seconds)
