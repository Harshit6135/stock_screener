"""Fail-closed portfolio guards over confirmed ledger state and durable intents."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError


def decimal(value):
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise DomainValidationError("risk input is not numeric") from exc
    if not result.is_finite():
        raise DomainValidationError("risk input must be finite")
    return result


def trading_date():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


class ManagedRiskGuard:
    def __init__(self, database, ledger, market, config, risk_reader):
        self.database, self.ledger, self.market = database, ledger, market
        self.config, self.risk_reader = config, risk_reader
        migrate_sqlite(database, "risk_reservations", {1: (
            """CREATE TABLE risk_reservations (
                reservation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                proposal_id TEXT NOT NULL, orders_json TEXT NOT NULL,
                ledger_version INTEGER NOT NULL, config_version INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE')""",
            "CREATE INDEX risk_reservations_account ON risk_reservations(account_id, status)",
        )})

    def release(self, reservation_id):
        with sqlite_connection(self.database) as connection:
            connection.execute("UPDATE risk_reservations SET status='RELEASED' WHERE reservation_id=?", (reservation_id,))

    def validate(self, account_id, orders, expected_version=None, *, reservation_id=None, proposal_id=""):
        # Immediate lock serializes concurrent approval/submission reservations
        # with ledger and configuration writes in the shared SQLite store.
        _result = None
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT COALESCE(MAX(version),0) FROM ledger_events WHERE account_id=?", (account_id,)).fetchone()[0]
            if expected_version is not None and current != expected_version:
                raise DomainValidationError("stale ledger version")
            config_version, limits = self.config.get_limits()
            pending = []
            for row in connection.execute("SELECT * FROM risk_reservations WHERE account_id=? AND status='ACTIVE'", (account_id,)):
                if row["reservation_id"] == reservation_id:
                    continue
                if proposal_id and row["proposal_id"] == proposal_id and row["reservation_id"].startswith("proposal:"):
                    continue
                pending.extend(json.loads(row["orders_json"]))
            projection = self.ledger.projection(account_id)
            holdings = {}
            for lot in projection.open_lots:
                item = holdings.setdefault(lot.instrument_id, {"units": 0, "acquired": lot.opened_on})
                item["units"] += lot.remaining_units.units
                item["acquired"] = max(item["acquired"], lot.opened_on)
            stops = {}
            projections = self.risk_reader(account_id) if self.risk_reader else []
            if projections:
                stops = {p["instrument_id"]: decimal(p["current_trailing_stop"]) for p in projections[0]["positions"]}
            for instrument, item in holdings.items():
                bars = self.market.bars(instrument, end_date=trading_date(), limit=1)
                if not bars:
                    raise DomainValidationError("held instrument has no valuation price")
                item["price"] = decimal(bars[-1]["close"])
                item["stop"] = stops.get(instrument)
                item["sector"] = self._sector(connection, instrument)
            cash = projection.cash.amount
            equity = cash + sum(item["units"] * item["price"] for item in holdings.values())
            buy_orders = []
            violations = []
            for order in pending + orders:
                side = order.get("side") or order.get("type")
                if side == "NO_ACTION":
                    continue
                is_buy = side in {"BUY", "PYRAMID_ADD"}
                instrument = str(order["instrument_id"])
                units = order.get("units", order.get("quantity"))
                if isinstance(units, bool) or not isinstance(units, int) or units <= 0:
                    raise DomainValidationError("guard order units must be positive integers")
                price = decimal(order.get("execution_price") or order.get("price"))
                if price <= 0:
                    raise DomainValidationError("guard order price must be positive")
                if not is_buy:
                    item = holdings.get(instrument)
                    if not item or item["units"] < units:
                        violations.append("sell exceeds unreserved managed units")
                        continue
                    if (limits.min_holding_period_days is not None and side not in {"UNIVERSE_EXIT", "STOP_LOSS", "HARD_STOP"}
                            and not order.get("protective") and order.get("exit_reason") not in {"universe_exit", "strategy_stop", "hard_stop"}
                            and (trading_date() - item["acquired"]).days < limits.min_holding_period_days):
                        violations.append("minimum holding period has not elapsed")
                    item["units"] -= units
                    # Unfilled sells are not buying power.
                    continue
                buy_orders.append(order)
                value = price * units + decimal(order.get("fee", 0))
                if limits.max_order_value is not None and value > decimal(limits.max_order_value):
                    violations.append("maximum order value exceeded")
                cash -= value
                item = holdings.setdefault(instrument, {"units": 0, "price": price, "acquired": trading_date(), "stop": None, "sector": self._sector(connection, instrument)})
                item["units"] += units
                stop = order.get("stop_price") or order.get("current_trailing_stop")
                if stop is not None:
                    item["stop"] = decimal(stop)
            if buy_orders:
                if cash < decimal(limits.min_reserve_cash or 0):
                    violations.append("insufficient unreserved cash or minimum reserve breached")
                live = [h for h in holdings.values() if h["units"] > 0]
                if limits.max_positions is not None and len(live) > limits.max_positions:
                    violations.append("maximum positions exceeded")
                sector_values = {}
                heat = Decimal(0)
                for item in live:
                    value = item["units"] * item["price"]
                    if limits.max_concentration is not None and (equity <= 0 or value > equity * decimal(limits.max_concentration)):
                        violations.append("maximum concentration exceeded")
                    if limits.max_sector_exposure is not None and not item["sector"]:
                        violations.append("sector evidence is missing")
                    sector_values[item["sector"]] = sector_values.get(item["sector"], Decimal(0)) + value
                    if limits.max_heat is not None:
                        if item["stop"] is None:
                            violations.append("stop evidence is missing")
                        else:
                            heat += max(Decimal(0), value - item["stop"] * item["units"])
                if limits.max_heat is not None and (equity <= 0 or heat > equity * decimal(limits.max_heat)):
                    violations.append("aggregate portfolio heat exceeded")
                if limits.max_sector_exposure is not None and any(v > equity * decimal(limits.max_sector_exposure) for v in sector_values.values()):
                    violations.append("maximum sector exposure exceeded")
                self._performance_limits(connection, account_id, equity, limits, violations)
            if violations:
                raise DomainValidationError("risk guard: " + "; ".join(sorted(set(violations))))
            if reservation_id:
                connection.execute("""INSERT INTO risk_reservations VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')
                    ON CONFLICT(reservation_id) DO UPDATE SET orders_json=excluded.orders_json,
                    ledger_version=excluded.ledger_version, config_version=excluded.config_version, status='ACTIVE'""",
                    (reservation_id, account_id, proposal_id, json.dumps(orders), current, config_version))
            # Capture equity/cash for post-transaction snapshot.
            _snap_equity, _snap_cash = equity, cash
            _snap_current, _snap_config = current, config_version
            _result = {"ledger_version": current, "config_version": config_version}
        # Persist today's valuation snapshot so daily-loss and drawdown
        # guards have prior-day evidence on subsequent validations.
        # Written outside the IMMEDIATE transaction to avoid lock contention.
        if _result is not None:
            try:
                today = trading_date()
                snapshot_id = f"guard:{account_id}:{today.isoformat()}"
                snap_payload = {"equity": str(_snap_equity), "cash": str(_snap_cash),
                                "ledger_version": _snap_current, "config_version": _snap_config}
                self.ledger.save_valuation(account_id, snapshot_id, today, snap_payload)
            except Exception:
                pass  # best-effort; snapshot already exists or DB unavailable
            return _result

    def _sector(self, connection, instrument):
        row = connection.execute("""SELECT m.industry FROM universe_snapshot_members m
            JOIN reference_instruments i ON i.isin=m.isin JOIN universe_snapshots s ON s.snapshot_id=m.snapshot_id
            WHERE i.instrument_id=? ORDER BY s.snapshot_date DESC LIMIT 1""", (instrument,)).fetchone()
        return row[0] if row else None

    def _performance_limits(self, connection, account_id, equity, limits, violations):
        if limits.max_daily_loss is None and limits.max_drawdown is None:
            return
        rows = connection.execute("SELECT as_of_date, payload_json FROM ledger_valuation_snapshots WHERE account_id=? AND as_of_date<? ORDER BY as_of_date", (account_id, trading_date().isoformat())).fetchall()
        if not rows:
            violations.append("prior valuation evidence is missing for loss/drawdown guards")
            return
        # Bring historical valuations to today's contributed-capital basis.
        adjusted = []
        for row in rows:
            net_flows = Decimal(0)
            for event in connection.execute("SELECT event_json FROM ledger_events WHERE account_id=? AND event_type='CASH_TRANSFER' AND substr(occurred_at,1,10)>? AND substr(occurred_at,1,10)<=?", (account_id, row["as_of_date"], trading_date().isoformat())):
                flow = json.loads(event[0])
                net_flows += decimal(flow["amount"]) * (1 if flow["direction"] == "DEPOSIT" else -1)
            adjusted.append(decimal(json.loads(row["payload_json"])["equity"]) + net_flows)
        if limits.max_daily_loss is not None and adjusted[-1] - equity > decimal(limits.max_daily_loss):
            violations.append("maximum daily loss exceeded")
        peak = max(adjusted + [equity])
        if limits.max_drawdown is not None and peak > 0 and (peak-equity)/peak > decimal(limits.max_drawdown):
            violations.append("maximum drawdown exceeded")
