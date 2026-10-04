"""Isolated, non-live acceptance probes for implemented repair paths.

This is not a unit-test completion gate. It records observable behavior using
a disposable local store and a fake broker; no network or live orders are used.
"""

from __future__ import annotations

import ast
import sys
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Flask

from src.domains.execution import KiteAccounts
from src.domains.market_data import NormalizedBar
from src.domains.portfolio_engine import RiskGuardLimits
from src.domains.reference_data import TrackedInstrument
from src.gates.composition import ApplicationServices
from src.gates.http.portfolio import create_portfolio_blueprint
from src.gates.workflows.broker_orders import BrokerOrderWorkflow
from src.gates.workflows.portfolio_sync import PortfolioSync
from src.platform_kernel import DomainValidationError, Money
from src.platform_kernel.sqlite import sqlite_connection


def rejected(action, label):
    try:
        action()
    except DomainValidationError:
        print("CONFIRMED:", label)
        return
    raise RuntimeError("Expected rejection: " + label)


class FakeKite:
    def __init__(self, api_key):
        self.api_key = api_key

    def set_access_token(self, token):
        self.token = token

    def profile(self):
        return {"user_id": "USER-" + self.api_key}

    def generate_session(self, request_token, api_secret):
        return {"access_token": "fixture-token"}

    def holdings(self):
        return [{"isin": "ISIN-ONE", "quantity": 5}]


def main():
    for path in (ROOT / "src").rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    print("CONFIRMED: source syntax")
    with tempfile.TemporaryDirectory(prefix=".phase-repair-probe-", dir=ROOT) as directory:
        app = ApplicationServices.create(directory)
        print("CONFIRMED: fresh application composition, live execution disabled")
        if app.broker_orders.execution_controls()["enabled"]:
            raise RuntimeError("Live execution unexpectedly enabled")
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1)
        app.market.upsert_instruments(
            [TrackedInstrument("share", "ISIN-ONE", "ONE", "NSE", "123", today)]
        )
        member = {
            "isin": "ISIN-ONE",
            "symbol": "ONE",
            "company_name": "One",
            "industry": "Technology",
            "series": "EQ",
        }
        app.market.create_universe_snapshot(
            snapshot_id="membership",
            index_name="NIFTY 500",
            snapshot_date=today,
            source_url="fixture://membership",
            raw_csv=b"fixture",
            members=[member],
        )

        def bar(day, price=100, volume=1):
            return NormalizedBar(
                "share", day, Decimal(price), Decimal(price), Decimal(price), Decimal(price), volume
            )

        volumes = [0, 0, 0, 1, 0, 0, 0]
        first = today - timedelta(days=10)
        app.market.upsert_bars(
            "share",
            [bar(first + timedelta(days=i), volume=value) for i, value in enumerate(volumes)],
            "bars-a",
        )
        app.market.upsert_bars("share", [bar(first + timedelta(days=7), volume=0)], "bars-b")
        if app.market.quality_events(check_type="zero_volume_streak"):
            raise RuntimeError("Non-contiguous zeros produced a streak")
        print("CONFIRMED: non-contiguous zero-volume rows do not form a false streak")
        app.market.upsert_bars("share", [bar(today)], "latest")
        if app.market.bars("share", limit=1)[0]["as_of_date"] != today.isoformat():
            raise RuntimeError("Bounded bar read did not return newest data")
        print("CONFIRMED: bounded valuation reads return newest bars")

        app.ledger.open_account("risk-account", Money(Decimal(1000)))
        guard = app.actions.risk_guard
        version, _ = app.actions.risk_config.get_limits()
        app.actions.risk_config.update_limits(RiskGuardLimits(max_order_value=150), version)
        rejected(
            lambda: app.actions.risk_config.update_limits(RiskGuardLimits(), version),
            "stale configuration rejected atomically",
        )
        rejected(
            lambda: RiskGuardLimits(max_order_value=float("nan")), "non-finite risk limit rejected"
        )
        rejected(
            lambda: guard.validate(
                "risk-account",
                [{"type": "BUY", "instrument_id": "share", "units": 2, "price": "100"}],
                0,
            ),
            "real proposal guard rejects maximum order breach",
        )
        version, _ = app.actions.risk_config.get_limits()
        app.actions.risk_config.update_limits(RiskGuardLimits(min_reserve_cash=100), version)
        guard.validate(
            "risk-account",
            [{"type": "BUY", "instrument_id": "share", "units": 8, "price": "100"}],
            0,
            reservation_id="first",
        )
        rejected(
            lambda: guard.validate(
                "risk-account",
                [{"type": "BUY", "instrument_id": "share", "units": 2, "price": "100"}],
                0,
                reservation_id="second",
            ),
            "durable reservation prevents cash double allocation",
        )
        guard.release("first")

        event = app.corporate_actions.detect_events(
            [
                {
                    "symbol": "ONE",
                    "isin": "ISIN-ONE",
                    "action_type": "SPLIT",
                    "ex_date": today.isoformat(),
                    "ratio": "1:2",
                }
            ]
        )["events"][0]
        event_id = event["event_id"]
        app.corporate_actions.apply_self_adjustment(event_id)
        before = app.market.bars("share", limit=1000)
        app.market.adjust_corporate_event(event_id, 0.5)
        if before != app.market.bars("share", limit=1000):
            raise RuntimeError("Repeated adjustment changed prices")
        print("CONFIRMED: persisted state prevents repeated split adjustment")
        refreshed = [
            {
                "as_of_date": row["as_of_date"],
                "open": "50",
                "high": "50",
                "low": "50",
                "close": "50",
                "volume": 1,
            }
            for row in before
        ]
        result = app.corporate_actions.verify_with_kite(event_id, lambda *args: refreshed)
        if (
            result["state"] != "VERIFIED"
            or Decimal(app.market.bars("share", limit=1)[0]["close"]) != 50
        ):
            raise RuntimeError("Provider history was not replaced before verification")
        print("CONFIRMED: corporate verification persists replacement history")

        accounts = KiteAccounts(str(app.database), client_factory=FakeKite)
        accounts.register_account("broker", "Fixture", "fixture-key", "fixture-secret")
        accounts.authenticate("broker", "fixture-request")
        sync = PortfolioSync(app.database, accounts, app.ledger, app.market)
        payload = {
            "broker_account_id": "broker",
            "strategy_id": "momentum",
            "opening_cash": "500",
            "positions": [
                {
                    "instrument_id": "share",
                    "units": 5,
                    "unit_cost": "40",
                    "acquisition_date": first.isoformat(),
                    "provenance": "fixture",
                }
            ],
            "idempotency_key": "setup",
        }
        result = sync.setup(payload)
        if (
            sync.setup(payload) != result
            or app.ledger.projection(result["ledger_account_id"]).cash.amount != 500
        ):
            raise RuntimeError("Setup retry or imported cost cash basis changed")
        rejected(
            lambda: sync.setup({**payload, "idempotency_key": "another"}),
            "completed setup cannot import twice",
        )
        accounts.register_account("broker", "Renamed", "fixture-key", "fixture-secret")
        accounts.validate("broker")
        print("CONFIRMED: account rename retains linked session; setup import does not spend cash")
        web = Flask("repair-probes")
        web.register_blueprint(
            create_portfolio_blueprint(
                app.ledger, app.market, app.actions.risk_projection, app.actions.risk_config
            )
        )
        client = web.test_client()
        response = client.get(
            f"/api/portfolio/accounts/{result['ledger_account_id']}/valuation?as_of_date={datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()}"
        )
        if (
            response.status_code != 200
            or response.get_json()["holdings"][0]["acquisition_date"] != first.isoformat()
        ):
            raise RuntimeError("Portfolio valuation/API acquisition contract failed")
        print(
            "CONFIRMED: valuation API renders imported dates and explicit unavailable day-P&L basis"
        )

        with sqlite_connection(app.database) as connection:
            connection.execute("ALTER TABLE broker_orders DROP COLUMN variety")
            connection.execute(
                "DELETE FROM system_schema_migrations WHERE namespace='broker_orders' AND version>=2"
            )
        BrokerOrderWorkflow(app.database, app.ledger)
        with sqlite_connection(app.database, read_only=True) as connection:
            if "variety" not in {
                row[1] for row in connection.execute("PRAGMA table_info(broker_orders)")
            }:
                raise RuntimeError("Version-one broker store was not upgraded")
        print("CONFIRMED: existing version-one broker store receives variety migration")
    print("These probes do not certify pending replay, reconciliation or browser workflows.")


if __name__ == "__main__":
    main()
