from datetime import date

import pytest
from flask import Flask

from src.application.broker_web import create_broker_blueprint
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.execution_gateway import BrokerOrderService, Ledger
from src.platform_kernel import DomainValidationError, Money


class FakeBroker:
    def submit_order(self, order):
        return "broker-1"

    def order_status(self, broker_order_id):
        return {"status": "PARTIAL", "fills": [{"trade_id": "trade-1", "quantity": 2, "price": "10", "fill_date": "2026-09-10"}]}


def _intent():
    return {"account_id": "paper", "proposal_id": "proposal-1", "idempotency_key": "order-1", "instrument_id": "instrument-1", "symbol": "ABC", "exchange": "NSE", "side": "BUY", "quantity": 2, "order_type": "MARKET"}


def _seed_current_members(database):
    market = MarketRepository(database)
    observed = date(2026, 9, 9)
    market.upsert_instruments([
        TrackedInstrument("instrument-1", "INE000000001", "ABC", "NSE", "1", observed),
        TrackedInstrument("instrument-2", "INE000000002", "XYZ", "NSE", "2", observed),
    ])
    market.create_universe_snapshot(
        snapshot_id="broker-current", index_name="NIFTY 500", snapshot_date=observed,
        source_url="fixture://nse", raw_csv=b"ABC,XYZ",
        members=[{"isin": isin, "symbol": symbol, "company_name": symbol,
                  "industry": "IT", "series": "EQ"}
                 for isin, symbol in (("INE000000001", "ABC"), ("INE000000002", "XYZ"))],
    )
    return market


def test_broker_reconciliation_posts_each_trade_once(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(100))
    _seed_current_members(database)
    orders = BrokerOrderService(database, ledger, FakeBroker())
    order = orders.create_intent(_intent())
    assert orders.create_intent(_intent())["order_id"] == order["order_id"]
    assert orders.submit(order["order_id"])["broker_order_id"] == "broker-1"
    assert orders.reconcile(order["order_id"])["status"] == "PARTIALLY_FILLED"
    orders.reconcile(order["order_id"])
    assert ledger.projection("paper").open_lots[0].remaining_units.units == 2


def test_kite_gateway_is_disabled_by_default(tmp_path):
    from src.application.kite_auth import KiteCredentials
    from src.execution_gateway import KiteExecutionGateway
    from src.platform_kernel import DomainValidationError

    gateway = KiteExecutionGateway(KiteCredentials("key", "secret"), tmp_path / "token")
    try:
        gateway.submit_order(_intent())
    except DomainValidationError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("disabled gateway accepted an order")


def test_kite_gateway_fails_closed_on_kill_switch_and_allowlists(tmp_path):
    from src.application.kite_auth import KiteCredentials
    from src.execution_gateway import KiteExecutionGateway
    from src.platform_kernel import DomainValidationError

    class Client:
        def set_access_token(self, token):
            assert token == "token"

        def place_order(self, **kwargs):
            assert kwargs["tradingsymbol"] == "ABC"
            return "kite-order-1"

    token_path = tmp_path / "token"
    token_path.write_text("token", encoding="utf-8")
    gateway = KiteExecutionGateway(
        KiteCredentials("key", "secret"),
        token_path,
        enabled=True,
        client_factory=lambda **_: Client(),
        allowed_accounts=("paper",),
        allowed_instruments=("instrument-1",),
    )
    assert gateway.controls() == {
        "enabled": True,
        "kill_switch": True,
        "allowlisted_account_count": 1,
        "allowlisted_instrument_count": 1,
    }
    with pytest.raises(DomainValidationError, match="kill switch"):
        gateway.submit_order(_intent())
    gateway.arm()
    assert gateway.submit_order(_intent()) == "kite-order-1"
    with pytest.raises(DomainValidationError, match="allowlisted"):
        gateway.submit_order({**_intent(), "account_id": "other"})
    gateway.disarm()


def test_execution_controls_readback_is_operator_protected(tmp_path):
    database = tmp_path / "system.db"
    orders = BrokerOrderService(database, Ledger(database), FakeBroker())
    app = Flask(__name__)
    app.register_blueprint(create_broker_blueprint(orders))
    client = app.test_client()
    assert client.get("/api/v2/portfolio/execution-controls").status_code == 200
    response = client.get("/api/v2/portfolio/execution-controls")
    assert response.status_code == 200
    assert response.json["gateway"] == "FakeBroker"


def test_policy_rejection_does_not_become_submit_unknown(tmp_path):
    from src.platform_kernel import DomainValidationError

    class RejectingBroker:
        def submit_order(self, _order):
            raise DomainValidationError("kill switch is active")

    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(100))
    _seed_current_members(database)
    orders = BrokerOrderService(database, ledger, RejectingBroker())
    order = orders.create_intent(_intent())
    with pytest.raises(DomainValidationError, match="kill switch"):
        orders.submit(order["order_id"])
    assert orders.get(order["order_id"])["status"] == "LOCAL_CREATED"


def test_twap_basket_is_idempotent_and_submits_one_slice(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(1000))
    _seed_current_members(database)
    orders = BrokerOrderService(database, ledger, FakeBroker())
    base = {
        "account_id": "paper", "proposal_id": "proposal-1", "idempotency_key": "basket-1",
        "execution_mode": "TWAP", "slice_count": 2, "interval_seconds": 60,
        "orders": [{**_intent(), "idempotency_key": "ignored"}, {**_intent(), "instrument_id": "instrument-2", "symbol": "XYZ", "idempotency_key": "ignored-2"}],
    }
    first = orders.create_basket(base)
    second = orders.create_basket(base)
    assert first["basket_id"] == second["basket_id"]
    assert len(first["orders"]) == 2
    assert orders.submit_basket(first["basket_id"], 0)["orders"][0]["status"] == "SUBMITTED"


def test_approved_buy_intent_is_blocked_when_membership_changes_before_submit(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(100))
    market = _seed_current_members(database)
    calls = []

    class Broker:
        def submit_order(self, order):
            calls.append(order)
            return "should-not-submit"

    orders = BrokerOrderService(database, ledger, Broker())
    order = orders.create_intent(_intent())
    market.create_universe_snapshot(
        snapshot_id="broker-after-removal", index_name="NIFTY 500",
        snapshot_date=date(2026, 9, 10), source_url="fixture://nse", raw_csv=b"XYZ",
        members=[{"isin": "INE000000002", "symbol": "XYZ", "company_name": "XYZ",
                  "industry": "IT", "series": "EQ"}],
    )
    with pytest.raises(DomainValidationError, match="outside the current NSE snapshot"):
        orders.submit(order["order_id"])
    assert calls == []
    assert orders.get(order["order_id"])["status"] == "LOCAL_CREATED"
