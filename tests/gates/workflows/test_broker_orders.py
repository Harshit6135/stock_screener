from datetime import date

import pytest

from src.domains.portfolio_accounting import Ledger
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.broker_orders import BrokerOrderWorkflow
from src.platform_kernel import DomainValidationError, Money


def _intent():
    return {
        "account_id": "paper",
        "proposal_id": "proposal-1",
        "idempotency_key": "order-1",
        "instrument_id": "instrument-1",
        "symbol": "ABC",
        "exchange": "NSE",
        "side": "BUY",
        "quantity": 2,
        "order_type": "MARKET",
    }


class FakeBroker:
    def submit_order(self, order):
        return "broker-1"

    def order_status(self, broker_order_id):
        return {
            "status": "PARTIAL",
            "fills": [
                {"trade_id": "trade-1", "quantity": 2, "price": "10", "fill_date": "2026-09-10"}
            ],
        }


def _seed_current_members(database):
    market = MarketRepository(database)
    observed = date(2026, 9, 9)
    market.upsert_instruments(
        [
            TrackedInstrument("instrument-1", "INE000000001", "ABC", "NSE", "1", observed),
            TrackedInstrument("instrument-2", "INE000000002", "XYZ", "NSE", "2", observed),
        ]
    )
    market.create_universe_snapshot(
        snapshot_id="broker-current",
        index_name="NIFTY 500",
        snapshot_date=observed,
        source_url="fixture://nse",
        raw_csv=b"ABC,XYZ",
        members=[
            {
                "isin": isin,
                "symbol": symbol,
                "company_name": symbol,
                "industry": "IT",
                "series": "EQ",
            }
            for isin, symbol in (("INE000000001", "ABC"), ("INE000000002", "XYZ"))
        ],
    )
    return market


def test_broker_reconciliation_posts_each_trade_once(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(100))
    _seed_current_members(database)
    orders = BrokerOrderWorkflow(database, ledger, FakeBroker())
    order = orders.create_intent(_intent())
    assert orders.create_intent(_intent())["order_id"] == order["order_id"]
    assert orders.submit(order["order_id"])["broker_order_id"] == "broker-1"
    assert orders.reconcile(order["order_id"])["status"] == "PARTIALLY_FILLED"
    orders.reconcile(order["order_id"])
    assert ledger.projection("paper").open_lots[0].remaining_units.units == 2


def test_kite_gateway_is_disabled_by_default(tmp_path):
    from src.domains.execution import KiteCredentials, KiteExecutionGateway
    from src.platform_kernel import DomainValidationError

    gateway = KiteExecutionGateway(KiteCredentials("key", "secret"), tmp_path / "token")
    try:
        gateway.submit_order(_intent())
    except DomainValidationError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("disabled gateway accepted an order")


def test_kite_gateway_fails_closed_on_kill_switch_and_allowlists(tmp_path):
    from src.domains.execution import KiteCredentials, KiteExecutionGateway
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


def test_policy_rejection_does_not_become_submit_unknown(tmp_path):
    from src.platform_kernel import DomainValidationError

    class RejectingBroker:
        def submit_order(self, _order):
            raise DomainValidationError("kill switch is active")

    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(100))
    _seed_current_members(database)
    orders = BrokerOrderWorkflow(database, ledger, RejectingBroker())
    order = orders.create_intent(_intent())
    with pytest.raises(DomainValidationError, match="kill switch"):
        orders.submit(order["order_id"])
    assert orders.get(order["order_id"])["status"] == "LOCAL_CREATED"


def test_twap_basket_is_idempotent_and_submits_one_slice(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(1000))
    _seed_current_members(database)
    orders = BrokerOrderWorkflow(database, ledger, FakeBroker())
    base = {
        "account_id": "paper",
        "proposal_id": "proposal-1",
        "idempotency_key": "basket-1",
        "execution_mode": "TWAP",
        "slice_count": 2,
        "interval_seconds": 60,
        "orders": [
            {**_intent(), "idempotency_key": "ignored"},
            {
                **_intent(),
                "instrument_id": "instrument-2",
                "symbol": "XYZ",
                "idempotency_key": "ignored-2",
            },
        ],
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

    orders = BrokerOrderWorkflow(database, ledger, Broker())
    order = orders.create_intent(_intent())
    market.create_universe_snapshot(
        snapshot_id="broker-after-removal",
        index_name="NIFTY 500",
        snapshot_date=date(2026, 9, 10),
        source_url="fixture://nse",
        raw_csv=b"XYZ",
        members=[
            {
                "isin": "INE000000002",
                "symbol": "XYZ",
                "company_name": "XYZ",
                "industry": "IT",
                "series": "EQ",
            }
        ],
    )
    with pytest.raises(DomainValidationError, match="outside the current NSE snapshot"):
        orders.submit(order["order_id"])
    assert calls == []
    assert orders.get(order["order_id"])["status"] == "LOCAL_CREATED"


def test_broker_receipt_recovery_uses_the_same_stable_tag_as_submission(tmp_path):
    from src.domains.execution import KiteCredentials, KiteExecutionGateway

    token = tmp_path / "token"
    token.write_text("fixture-token")

    class Client:
        def set_access_token(self, value):
            assert value == "fixture-token"

        def place_order(self, **payload):
            self.tag = payload["tag"]
            return "receipt"

        def orders(self):
            return [{"tag": self.tag, "order_id": "receipt"}]

    client = Client()
    gateway = KiteExecutionGateway(
        KiteCredentials("key", "secret"),
        token,
        enabled=True,
        client_factory=lambda **_: client,
        allowed_accounts=["account"],
        allowed_instruments=["share"],
    )
    gateway.arm()
    order = {
        "account_id": "account",
        "instrument_id": "share",
        "idempotency_key": "retry",
        "exchange": "NSE",
        "symbol": "SHARE",
        "side": "BUY",
        "quantity": 1,
        "order_type": "MARKET",
    }
    assert gateway.submit_order(order) == gateway.find_order(order) == "receipt"
    assert gateway._order_tag({**order, "order_id": "existing-order-id"}) == "existingorderid"
