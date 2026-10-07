from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.domains.portfolio_engine import PortfolioRiskConfig
from src.gates.http.actions import create_actions_blueprint
from src.gates.repositories import MarketRepository, NormalizedBar, TrackedInstrument
from src.gates.workflows.broker_orders import BrokerOrderWorkflow
from src.gates.workflows.managed_risk import ManagedRiskGuard
from src.gates.workflows.portfolio_actions import ActionJobs
from src.gates.workflows.stop_sells import StopSellWorkflow
from src.platform_kernel import ArtifactStore, DomainValidationError, Money, Quantity

NOW = datetime(2026, 3, 11, 10, tzinfo=ZoneInfo("Asia/Kolkata"))


class Kite:
    def __init__(self):
        self.price, self.quantity, self.stamp = 95, 3, NOW
        self.calls, self.pending, self.fills = [], [], []
        self.status, self.fail = "OPEN", False

    def quote(self, symbols):
        return {"NSE:ABC": {"last_price": self.price, "timestamp": self.stamp}}

    def holdings(self):
        return [{"tradingsymbol": "ABC", "exchange": "NSE", "quantity": self.quantity}]

    def positions(self):
        return {"net": []}

    def orders(self):
        return self.pending

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise TimeoutError("uncertain receipt")
        return "kite-1"

    def order_history(self, order_id):
        return [{"status": self.status}]

    def order_trades(self, order_id):
        return self.fills

    def margins(self, segment):
        return {"net": 1000}


class Accounts:
    def __init__(self, kite):
        self.kite, self.expired = kite, False

    def binding(self, account_id):
        raise DomainValidationError("no strategy binding")

    def get_credentials(self, account_id):
        assert account_id == "account"
        return {}

    def validate(self, account_id):
        if self.expired:
            raise DomainValidationError("selected broker session is expired")

    def client(self, account_id):
        assert account_id == "account"
        return self.kite


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from src.gates.workflows import portfolio_stops, stop_sells

    class Clock:
        @staticmethod
        def now(zone):
            return NOW

    monkeypatch.setattr(stop_sells, "india_now", lambda: NOW)
    monkeypatch.setattr(portfolio_stops, "datetime", Clock)
    database = tmp_path / "portfolio.db"
    ledger, market = Ledger(database), MarketRepository(database)
    ledger.open_account("account", Money(1000), date(2026, 2, 1))
    market.upsert_instruments(
        [TrackedInstrument("abc", "ABC", "ABC", "NSE", "1", date(2026, 2, 1))]
    )
    ledger.record_fills(
        "account", "buy", 0, [Fill("abc", date(2026, 2, 20), FillSide.BUY, Quantity(3), Money(100))]
    )
    market.upsert_bars(
        "abc",
        [
            NormalizedBar(
                "abc", date(2026, 2, 1) + timedelta(days=i), close, close + 1, close - 1, close, 100
            )
            for i, close in enumerate([100] * 19 + [110] * 10 + [95] * 9)
        ],
        "prices",
    )
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    actions = ActionJobs(database, market, None, ledger, publisher)
    orders = BrokerOrderWorkflow(database, ledger, market=market)
    guard = ManagedRiskGuard(
        database, ledger, market, PortfolioRiskConfig(str(database)), actions.risk_projection
    )
    actions.risk_guard = orders.risk_guard = guard
    kite = Kite()
    workflow = StopSellWorkflow(actions, orders, Accounts(kite))
    app = Flask(__name__)
    app.register_blueprint(create_actions_blueprint(actions, workflow))
    return workflow, kite, app.test_client()


def proposal(workflow):
    return workflow.check("account")["proposals"][0]


def test_breach_creates_single_review_action_without_trading(setup):
    workflow, kite, client = setup
    first = proposal(workflow)
    assert first["status"] == "PENDING"
    assert first["decisions"][0]["units"] == 3
    assert first["decisions"][0]["type"] == "HARD_STOP"
    assert first["decisions"][0]["price_source"] == "live_kite"
    assert proposal(workflow)["proposal_id"] == first["proposal_id"]
    assert not kite.calls
    response = client.post("/api/actions/stops/check", json={"account_id": "account"})
    assert response.status_code == 200 and response.json["submitted"] is False


def test_stop_check_explains_empty_queue_when_live_price_is_above_stop(setup):
    workflow, kite, client = setup
    kite.price = 120
    response = client.post("/api/actions/stops/check", json={"account_id": "account"})
    assert response.status_code == 200
    assert response.json["proposals"] == []
    check = response.json["checks"][0]
    assert check["symbol"] == "ABC"
    assert check["price"] == "120"
    assert check["status"] == "above_stop"
    assert check["price_source"] == "live_kite"
    assert Decimal(check["stop_threshold"]) < 120
    assert workflow.actions.proposals("account") == []
    assert not kite.calls


def test_current_stop_reviews_are_available_independently_of_strategy_date_filters(setup):
    _workflow, kite, client = setup
    response = client.post("/api/actions/stops/check", json={"account_id": "account"})
    assert response.json["checks"][0]["status"] == "breached"
    proposal_id = response.json["proposals"][0]["proposal_id"]
    filtered = client.get(
        "/api/actions/proposals?account_id=account&strategy_id=momentum&action_date=2026-03-12"
    )
    assert filtered.json["proposals"] == []
    repeated = client.post("/api/actions/stops/check", json={"account_id": "account"})
    assert repeated.json["proposals"][0]["proposal_id"] == proposal_id
    assert repeated.json["checks"][0]["status"] == "review_exists"
    assert not kite.calls


def test_approval_submits_once_and_only_confirmed_fills_change_ledger(setup):
    workflow, kite, client = setup
    pid = proposal(workflow)["proposal_id"]
    response = client.post(f"/api/actions/stops/{pid}/approve-execute", json={"approved": True})
    assert response.status_code == 202, response.json
    assert response.json["proposal"]["status"] == "APPROVED"
    assert response.json["order"]["status"] == "SUBMITTED"
    assert kite.calls[0]["quantity"] == 3
    assert kite.calls[0]["transaction_type"] == "SELL"
    assert kite.calls[0]["product"] == "CNC"
    assert kite.calls[0]["market_protection"] == -1
    workflow.approve_and_execute(pid)
    assert len(kite.calls) == 1
    assert workflow.ledger.projection("account").open_lots[0].remaining_units.units == 3
    kite.fills = [
        {
            "trade_id": "fill1",
            "quantity": 1,
            "fill_price": 95,
            "exchange_timestamp": "2026-03-11 10:00:01",
        }
    ]
    workflow.reconcile(pid)
    assert workflow.ledger.projection("account").open_lots[0].remaining_units.units == 2
    workflow.reconcile(pid)
    assert workflow.ledger.projection("account").open_lots[0].remaining_units.units == 2
    kite.fills.append(
        {
            "trade_id": "fill2",
            "quantity": 2,
            "fill_price": 94,
            "exchange_timestamp": "2026-03-11 10:00:02",
        }
    )
    kite.status = "COMPLETE"
    result = workflow.reconcile(pid)
    assert result["order"]["status"] == "FILLED"
    assert result["proposal"]["status"] == "PROCESSED"
    assert not workflow.ledger.projection("account").open_lots
    assert workflow.ledger.projection("account").cash.amount == Decimal(983)


@pytest.mark.parametrize(
    "condition",
    ["recovered", "expired", "shares", "stale_quote", "pending_sell", "stale_ledger", "closed"],
)
def test_preflight_failure_never_approves_or_trades(setup, monkeypatch, condition):
    workflow, kite, _ = setup
    pid = proposal(workflow)["proposal_id"]
    if condition == "recovered":
        kite.price = 120
    elif condition == "expired":
        workflow.accounts.expired = True
    elif condition == "shares":
        kite.quantity = 2
    elif condition == "stale_quote":
        kite.stamp = NOW - timedelta(minutes=3)
    elif condition == "pending_sell":
        kite.pending = [
            {
                "tradingsymbol": "ABC",
                "exchange": "NSE",
                "transaction_type": "SELL",
                "quantity": 1,
                "status": "OPEN",
            }
        ]
    elif condition == "stale_ledger":
        workflow.ledger.record_fills(
            "account",
            "extra",
            1,
            [Fill("abc", date(2026, 3, 11), FillSide.BUY, Quantity(1), Money(95))],
        )
    else:
        monkeypatch.setattr(
            "src.gates.workflows.stop_sells.india_now", lambda: NOW.replace(hour=16)
        )
    with pytest.raises(DomainValidationError):
        workflow.approve_and_execute(pid)
    assert not kite.calls
    assert workflow.store.get(pid)["status"] == "PENDING"


def test_rejection_and_uncertain_submission_are_not_retried(setup):
    workflow, kite, _ = setup
    pid = proposal(workflow)["proposal_id"]
    kite.fail = True
    with pytest.raises(DomainValidationError, match="outcome is unknown"):
        workflow.approve_and_execute(pid)
    assert workflow.approve_and_execute(pid)["order"]["status"] == "SUBMIT_UNKNOWN"
    assert len(kite.calls) == 1


def test_rejected_sell_never_executes(setup):
    workflow, kite, _ = setup
    pid = proposal(workflow)["proposal_id"]
    workflow.actions.decide(pid, "REJECTED")
    with pytest.raises(DomainValidationError, match="rejected"):
        workflow.approve_and_execute(pid)
    assert proposal(workflow)["status"] == "REJECTED"
    assert not kite.calls


def test_next_day_retires_unsubmitted_review_and_creates_fresh_action(setup, monkeypatch):
    workflow, kite, _ = setup
    old = proposal(workflow)
    monkeypatch.setattr("src.gates.workflows.stop_sells.india_now", lambda: NOW + timedelta(days=1))
    current = proposal(workflow)
    assert current["proposal_id"] != old["proposal_id"]
    assert workflow.store.get(old["proposal_id"])["status"] == "EXPIRED"
    assert current["action_date"] == "2026-03-12"
    assert not kite.calls


def test_background_monitor_detects_but_never_submits_and_reconciles_confirmed_fills(setup):
    from src.gates.workflows.stop_sells import BackgroundStopMonitor

    workflow, kite, _ = setup
    monitor = BackgroundStopMonitor(workflow)
    monitor.tick()
    pid = proposal(workflow)["proposal_id"]
    assert not kite.calls
    workflow.approve_and_execute(pid)
    kite.fills = [
        {
            "trade_id": "monitor-fill",
            "quantity": 3,
            "fill_price": 95,
            "exchange_timestamp": "2026-03-11 10:00:01",
        }
    ]
    kite.status = "COMPLETE"
    kite.price = 120
    # An open receipt stays visible if price recovers after submission.
    assert proposal(workflow)["broker_order"]["status"] == "SUBMITTED"
    monitor.tick()
    assert workflow.store.get(pid)["status"] == "PROCESSED"
    assert not workflow.ledger.projection("account").open_lots
    assert len(kite.calls) == 1


@pytest.fixture
def execution(setup, monkeypatch):
    from src.gates.workflows import proposal_execution

    stops, kite, _ = setup
    monkeypatch.setattr(proposal_execution, "india_now", lambda: NOW)
    flow = proposal_execution.ProposalExecution(stops)
    return flow, kite


def strategy_proposal(flow, target="2026-03-11", extra=False, side="SELL"):
    decisions = [
        {
            "type": side,
            "instrument_id": "abc",
            "symbol": "ABC",
            "units": 3 if side == "SELL" else 1,
            "execution_price": "100",
            "fee": "0",
            "reason": "Strategy signal",
        }
    ]
    if extra:
        decisions.append(
            {
                "type": "SELL",
                "instrument_id": "none",
                "symbol": "NONE",
                "units": 1,
                "execution_price": "100",
                "reason": "Other stock to review",
            }
        )
    flow.stops.store.recover_pending(
        proposal_id="strategy",
        account_id="account",
        strategy_id="momentum",
        action_date=target,
        ranking_week_end="2026-03-10",
        expected_ledger_version=1,
        artifact_id="strategy",
        decisions=decisions,
        timestamp=NOW.isoformat(),
        event_type="GENERATED",
    )
    return "strategy"


def test_existing_strategy_approval_executes_and_reconciles(execution):
    flow, kite = execution
    pid = strategy_proposal(flow)
    result = flow.request(pid)
    assert result["execution"]["status"] == "SUBMITTED"
    assert len(kite.calls) == 1 and kite.calls[0]["transaction_type"] == "SELL"
    assert kite.calls[0]["variety"] == "regular"
    flow.request(pid)
    assert len(kite.calls) == 1
    kite.status = "COMPLETE"
    kite.fills = [
        {
            "trade_id": "strategy-fill",
            "quantity": 3,
            "fill_price": 95,
            "exchange_timestamp": "2026-03-11 10:00:01",
        }
    ]
    flow.tick()
    assert flow.readback(flow.stops.store.get(pid))["execution"]["status"] == "COMPLETE"
    assert flow.stops.store.get(pid)["status"] == "PROCESSED"
    assert not flow.stops.ledger.projection("account").open_lots


def test_stock_approval_waits_for_remaining_reviews(execution):
    flow, kite = execution
    pid = strategy_proposal(flow, extra=True)
    result = flow.request(pid, 0)
    assert result["status"] == "PENDING" and not kite.calls
    flow.tick()
    assert not kite.calls
    flow.stops.actions.decide_stock(pid, 1, "REJECTED")
    flow.tick()
    assert len(kite.calls) == 1 and kite.calls[0]["quantity"] == 3


def test_non_trading_rows_do_not_block_strategy_execution(execution):
    import json

    from src.platform_kernel.sqlite import sqlite_connection

    flow, kite = execution
    pid = strategy_proposal(flow)
    with sqlite_connection(flow.database) as connection:
        decisions = flow.stops.store.get(pid)["decisions"] + [
            {"type": "NO_ACTION", "instrument_id": "none", "reason": "No trade"}
        ]
        connection.execute(
            "UPDATE action_proposals SET decision_json=? WHERE proposal_id=?",
            (json.dumps(decisions), pid),
        )
    flow.request(pid, 0)
    assert len(kite.calls) == 1
    assert flow.stops.store.get(pid)["decision_statuses"] == ["APPROVED", "REJECTED"]


def test_future_strategy_orders_wait_until_target_session(execution, monkeypatch):
    flow, kite = execution
    pid = strategy_proposal(flow, target="2026-03-12")
    assert flow.request(pid)["execution"]["status"] == "QUEUED"
    assert not kite.calls
    next_day = NOW + timedelta(days=1)
    monkeypatch.setattr("src.gates.workflows.proposal_execution.india_now", lambda: next_day)
    monkeypatch.setattr("src.gates.workflows.stop_sells.india_now", lambda: next_day)
    kite.stamp = next_day
    flow.tick()
    assert len(kite.calls) == 1


def test_legacy_approval_alone_does_not_arm_background_execution(execution):
    flow, kite = execution
    pid = strategy_proposal(flow)
    flow.stops.actions.decide(pid, "APPROVED")
    flow.tick()
    assert not kite.calls


def test_strategy_buy_uses_fresh_cash_and_approved_stock_only(execution, monkeypatch):
    flow, kite = execution
    pid = strategy_proposal(flow, side="BUY")
    monkeypatch.setattr(flow.stops.actions, "_current_buy_members", lambda: ("snapshot", {"abc"}))
    monkeypatch.setattr(
        flow.stops.market, "latest_universe_snapshot", lambda universe: {"snapshot_id": "snapshot"}
    )
    monkeypatch.setattr(
        flow.stops.market, "universe_snapshot_members", lambda *args, **kwargs: [{"isin": "ABC"}]
    )
    flow.request(pid)
    assert len(kite.calls) == 1
    assert kite.calls[0]["transaction_type"] == "BUY" and kite.calls[0]["quantity"] == 1


def test_strategy_changed_portfolio_blocks_queued_execution(execution):
    flow, kite = execution
    pid = strategy_proposal(flow, target="2026-03-12")
    flow.request(pid)
    flow.stops.ledger.record_fills(
        "account",
        "outside",
        1,
        [Fill("abc", date(2026, 3, 11), FillSide.BUY, Quantity(1), Money(95))],
    )
    flow.tick()
    result = flow.readback(flow.stops.store.get(pid))
    assert result["execution"]["status"] == "BLOCKED"
    assert "outside this proposal" in result["execution"]["last_error"]
    assert not kite.calls


@pytest.mark.parametrize("condition", ["cash", "price"])
def test_strategy_buy_blocks_insufficient_live_cash_or_moved_quote(
    execution, monkeypatch, condition
):
    flow, kite = execution
    pid = strategy_proposal(flow, side="BUY")
    monkeypatch.setattr(flow.stops.actions, "_current_buy_members", lambda: ("snapshot", {"abc"}))
    monkeypatch.setattr(
        flow.stops.market, "latest_universe_snapshot", lambda universe: {"snapshot_id": "snapshot"}
    )
    monkeypatch.setattr(
        flow.stops.market, "universe_snapshot_members", lambda *args, **kwargs: [{"isin": "ABC"}]
    )
    if condition == "cash":
        monkeypatch.setattr(kite, "margins", lambda segment: {"net": 50})
    else:
        kite.price = 120
    result = flow.request(pid)
    assert result["execution"]["status"] == "BLOCKED"
    assert not kite.calls
    flow.tick()
    assert not kite.calls


def test_json_and_same_origin_approval_required(setup):
    workflow, kite, client = setup
    pid = proposal(workflow)["proposal_id"]
    path = f"/api/actions/stops/{pid}/approve-execute"
    assert client.post(path).status_code == 400
    assert (
        client.post(
            path, json={"approved": True}, headers={"Origin": "https://another-site.example"}
        ).status_code
        == 403
    )
    assert not kite.calls


def test_existing_strategy_http_approval_route(execution):
    flow, kite = execution
    pid = strategy_proposal(flow)
    app = Flask(__name__)
    app.register_blueprint(create_actions_blueprint(flow.stops.actions, flow.stops, flow))
    client = app.test_client()
    path = f"/api/actions/proposals/{pid}/approve-execute"
    assert client.post(path).status_code == 400
    response = client.post(path, json={"approved": True, "decision_index": 0})
    assert response.status_code == 202, response.json
    assert len(kite.calls) == 1
    rows = client.get("/api/actions/proposals?account_id=account").json["proposals"]
    assert rows[0]["execution"]["status"] == "SUBMITTED"


def test_strategy_sells_fill_before_buys_and_only_own_fills_rebase_version(execution, monkeypatch):
    flow, kite = execution
    pid = strategy_proposal(flow)
    flow.stops.market.upsert_instruments(
        [TrackedInstrument("bbb", "BBB", "BBB", "NSE", "2", date(2026, 2, 1))]
    )
    flow.stops.market.upsert_bars(
        "bbb", [NormalizedBar("bbb", date(2026, 3, 10), 95, 96, 94, 95, 100)], "prices"
    )
    import json

    from src.platform_kernel.sqlite import sqlite_connection

    with sqlite_connection(flow.database) as connection:
        decisions = flow.stops.store.get(pid)["decisions"] + [
            {
                "type": "BUY",
                "instrument_id": "bbb",
                "symbol": "BBB",
                "units": 1,
                "execution_price": "95",
                "fee": "0",
                "reason": "Replace exited holding",
            }
        ]
        connection.execute(
            "UPDATE action_proposals SET decision_json=? WHERE proposal_id=?",
            (json.dumps(decisions), pid),
        )
    monkeypatch.setattr(flow.stops.actions, "_current_buy_members", lambda: ("snapshot", {"bbb"}))
    monkeypatch.setattr(
        flow.stops.market, "latest_universe_snapshot", lambda universe: {"snapshot_id": "snapshot"}
    )
    monkeypatch.setattr(
        flow.stops.market, "universe_snapshot_members", lambda *args, **kwargs: [{"isin": "BBB"}]
    )
    monkeypatch.setattr(
        kite,
        "quote",
        lambda symbols: {key: {"last_price": 95, "timestamp": NOW} for key in symbols},
    )
    filled = {"sell": False}

    def place(**kwargs):
        kite.calls.append(kwargs)
        return "sell" if kwargs["transaction_type"] == "SELL" else "buy"

    monkeypatch.setattr(kite, "place_order", place)
    monkeypatch.setattr(
        kite, "order_history", lambda order: [{"status": "COMPLETE" if filled["sell"] else "OPEN"}]
    )
    monkeypatch.setattr(
        kite,
        "order_trades",
        lambda order: (
            []
            if not filled["sell"]
            else [
                {
                    "trade_id": "trade-" + order,
                    "quantity": 3 if order == "sell" else 1,
                    "fill_price": 95,
                    "exchange_timestamp": "2026-03-11 10:00:01",
                }
            ]
        ),
    )
    flow.request(pid)
    assert [row["transaction_type"] for row in kite.calls] == ["SELL"]
    filled["sell"] = True
    flow.tick()
    assert [row["transaction_type"] for row in kite.calls] == ["SELL", "BUY"]
    assert flow.stops.store.get(pid)["status"] == "PROCESSED"
    position = flow.stops.ledger.projection("account")
    assert position.cash.amount == 890
    assert [lot.instrument_id for lot in position.open_lots] == ["bbb"]
