"""Explicit approval requests connect existing strategy proposals to Kite."""

import json
from datetime import UTC, date, datetime, time
from decimal import Decimal

from src.domains.execution import KiteExecutionGateway
from src.gates.workflows.broker_orders import BrokerOrderWorkflow
from src.gates.workflows.stop_sells import india_now
from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class ApprovalRouting:
    def __init__(self, workflow, proposal):
        self.workflow, self.proposal = workflow, proposal

    def binding(self, account_id):
        if account_id != self.proposal["account_id"]:
            raise DomainValidationError("account does not match the approved proposal")
        return {
            "broker_account_id": self.workflow.stops.broker_account(account_id),
            "strategy_id": self.proposal["strategy_id"],
            "ledger_account_id": account_id,
        }

    def validate(self, account_id):
        return self.workflow.stops.accounts.validate(account_id)

    def client(self, account_id):
        return self.workflow.stops.accounts.client(account_id)


class ApprovedProposalGateway(KiteExecutionGateway):
    def __init__(self, workflow, proposal):
        self.workflow, self.proposal = workflow, proposal
        super().__init__(
            None,
            ".",
            enabled=True,
            accounts=ApprovalRouting(workflow, proposal),
            allowed_accounts=[proposal["account_id"]],
            allowed_instruments=[
                row["instrument_id"] for row in proposal["decisions"] if row["type"] != "NO_ACTION"
            ],
        )
        self.arm()

    def submit_order(self, order):
        proposal = self.workflow.current_proposal(self.proposal["proposal_id"])
        decision = next(
            (
                row
                for row, state in zip(
                    proposal["decisions"], proposal["decision_statuses"], strict=True
                )
                if state == "APPROVED"
                and row["instrument_id"] == order["instrument_id"]
                and (row["type"] in {"BUY", "PYRAMID_ADD"}) == (order["side"] == "BUY")
            ),
            None,
        )
        if (
            not decision
            or proposal["status"] != "APPROVED"
            or order["proposal_id"] != proposal["proposal_id"]
            or int(order["quantity"]) != int(decision["units"])
        ):
            raise DomainValidationError("order does not match an approved stock decision")
        client = self._client(str(order["account_id"]))
        price = self.workflow.stops.live_price(client, str(order["symbol"]))
        if order["side"] == "BUY":
            reference = Decimal(str(decision["execution_price"]))
            if abs(price / reference - 1) > Decimal("0.05"):
                raise DomainValidationError(
                    "buy quote moved more than 5% from the reviewed estimate; generate a fresh proposal"
                )
            live_funds = Decimal(str(client.margins("equity")["net"]))
            if price * int(order["quantity"]) > min(
                live_funds,
                self.workflow.stops.ledger.projection(proposal["account_id"]).cash.amount,
            ):
                raise DomainValidationError(
                    "live Kite funds or portfolio cash are insufficient for approved shares"
                )
        else:
            available = sum(
                int(row.get("quantity", 0)) + int(row.get("t1_quantity", 0))
                for row in client.holdings()
                if row.get("exchange") == "NSE" and row.get("tradingsymbol") == order["symbol"]
            )
            available += sum(
                int(row.get("quantity", 0))
                for row in client.positions().get("net", [])
                if row.get("exchange") == "NSE"
                and row.get("tradingsymbol") == order["symbol"]
                and row.get("product") == "CNC"
            )
            available -= sum(
                max(0, int(row.get("quantity", 0)) - int(row.get("filled_quantity", 0)))
                for row in client.orders()
                if row.get("exchange") == "NSE"
                and row.get("tradingsymbol") == order["symbol"]
                and row.get("transaction_type") == "SELL"
                and row.get("status") not in {"COMPLETE", "CANCELLED", "REJECTED"}
            )
            if available < int(order["quantity"]):
                raise DomainValidationError(
                    "Kite has fewer uncommitted shares than the approved sell"
                )
        if self.workflow.stops.orders.risk_guard:
            self.workflow.stops.orders.risk_guard.validate(
                proposal["account_id"],
                [{**decision, "execution_price": str(price)}],
                int(proposal["expected_ledger_version"]),
                reservation_id=f"broker:{order['order_id']}",
                proposal_id=proposal["proposal_id"],
            )
        return str(
            client.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=str(order["symbol"]),
                transaction_type=str(order["side"]),
                quantity=int(order["quantity"]),
                order_type="MARKET",
                product="CNC",
                validity="DAY",
                tag=self._order_tag(order),
                market_protection=-1,
            )
        )


class ProposalExecution:
    def __init__(self, stops):
        self.stops = stops
        self.database = stops.orders.database
        migrate_sqlite(
            self.database,
            "proposal_execution",
            {
                1: (
                    """CREATE TABLE proposal_execution_requests (
                proposal_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, details_version INTEGER NOT NULL,
                status TEXT NOT NULL, requested_at TEXT NOT NULL, last_error TEXT)""",
                )
            },
        )

    def current_proposal(self, proposal_id):
        proposal = self.stops.store.get(proposal_id)
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            request = connection.execute(
                "SELECT * FROM proposal_execution_requests WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            account = next(
                row
                for row in self.stops.ledger.accounts()
                if row["account_id"] == proposal["account_id"]
            )
            if not request or account.get("details_version", 0) != request["details_version"]:
                raise DomainValidationError(
                    "account details changed since execution approval; review and reapprove execution"
                )
            if account["version"] != proposal["expected_ledger_version"]:
                order_ids = {
                    row[0]
                    for row in connection.execute(
                        "SELECT order_id FROM broker_orders WHERE proposal_id=?", (proposal_id,)
                    )
                }
                commands = connection.execute(
                    "SELECT command_json FROM ledger_commands WHERE account_id=? AND resulting_version>?",
                    (proposal["account_id"], proposal["expected_ledger_version"]),
                ).fetchall()
                if not commands or any(
                    json.loads(row[0]).get("order_id") not in order_ids for row in commands
                ):
                    raise DomainValidationError(
                        "portfolio changed outside this proposal; generate fresh actions"
                    )
                # Only confirmed fills from this proposal may advance its execution baseline.
                proposal = {**proposal, "expected_ledger_version": account["version"]}
        return proposal

    def get(self, proposal_id):
        return self.current_proposal(proposal_id)

    def readback(self, proposal):
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM proposal_execution_requests WHERE proposal_id=?",
                (proposal["proposal_id"],),
            ).fetchone()
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT order_id FROM broker_orders WHERE proposal_id=?",
                    (proposal["proposal_id"],),
                )
            ]
        return {
            **proposal,
            "execution": dict(row) if row else None,
            "broker_orders": [self.stops.orders.get(order_id) for order_id in ids],
        }

    def request(self, proposal_id, decision_index=None):
        proposal = self.stops.store.get(proposal_id)
        if proposal["strategy_id"] in {"manual", "midweek_stop", "portfolio_stop"}:
            raise DomainValidationError("use the dedicated manual or stop review flow")
        if date.fromisoformat(proposal["action_date"]) < india_now().date():
            raise DomainValidationError(
                "this action is historical; generate actions for the current or next session"
            )
        self.stops.broker_account(proposal["account_id"])
        if not any(row["type"] != "NO_ACTION" for row in proposal["decisions"]):
            raise DomainValidationError("proposal contains no trades to execute")
        if decision_index is not None and (
            not 0 <= decision_index < len(proposal["decisions"])
            or proposal["decision_statuses"][decision_index] == "REJECTED"
        ):
            raise DomainValidationError("proposal stock row is invalid or rejected")
        if (
            decision_index is not None
            and proposal["decisions"][decision_index]["type"] == "NO_ACTION"
        ):
            raise DomainValidationError("this row contains no trade to approve")
        # Non-trading rows have no review button and cannot hold up approved trades.
        if proposal["status"] == "PENDING":
            for index, decision in enumerate(proposal["decisions"]):
                if (
                    decision["type"] == "NO_ACTION"
                    and proposal["decision_statuses"][index] == "PENDING"
                ):
                    proposal = self.stops.actions.decide_stock(proposal_id, index, "REJECTED")
        if proposal["status"] == "PENDING":
            if decision_index is None:
                proposal = self.stops.actions.decide(proposal_id, "APPROVED")
            elif proposal["decision_statuses"][decision_index] == "PENDING":
                proposal = self.stops.actions.decide_stock(proposal_id, decision_index, "APPROVED")
        elif proposal["status"] != "APPROVED":
            raise DomainValidationError("proposal is not awaiting execution")
        account = next(
            row
            for row in self.stops.ledger.accounts()
            if row["account_id"] == proposal["account_id"]
        )
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "INSERT INTO proposal_execution_requests VALUES (?,?,?,'QUEUED',?,NULL) ON CONFLICT(proposal_id) DO UPDATE SET status='QUEUED',last_error=NULL,details_version=excluded.details_version",
                (
                    proposal_id,
                    proposal["account_id"],
                    account.get("details_version", 0),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return self.process(proposal_id)

    def workflow(self, proposal):
        workflow = BrokerOrderWorkflow(
            self.database,
            self.stops.ledger,
            ApprovedProposalGateway(self, proposal),
            repository=self.stops.orders.repository,
            proposal_store=self,
            market=self.stops.market,
        )
        workflow.risk_guard = self.stops.orders.risk_guard
        return workflow

    def process(self, proposal_id):
        try:
            proposal = self.current_proposal(proposal_id)
            now = india_now()
            if (
                proposal["status"] == "PENDING"
                or date.fromisoformat(proposal["action_date"]) > now.date()
            ):
                return self.readback(proposal)
            if proposal["status"] != "APPROVED":
                raise DomainValidationError("proposal has no approved execution-ready stocks")
            if now.weekday() >= 5 or not time(9, 15) <= now.time() < time(15, 30):
                return self.readback(proposal)
            if (now.date() - date.fromisoformat(proposal["action_date"])).days > 7:
                raise DomainValidationError("queued execution has expired; generate fresh actions")
            workflow = self.workflow(proposal)
            existing = self.readback(proposal)["broker_orders"]
            orders = existing or workflow.prepare_proposal(proposal_id, regular_session=True)
            orders = sorted(orders, key=lambda row: row["side"] == "BUY")
            sells_waiting = False
            for order in orders:
                if order["side"] == "BUY" and sells_waiting:
                    continue
                if order["status"] == "LOCAL_CREATED":
                    order = workflow.submit(order["order_id"])
                if order["status"] in {
                    "SUBMITTED",
                    "PARTIALLY_FILLED",
                    "SUBMITTING",
                    "SUBMIT_UNKNOWN",
                }:
                    order = workflow.reconcile(order["order_id"])
                if order["status"] in {"CANCELLED", "REJECTED"}:
                    raise DomainValidationError(
                        "a broker order was cancelled or rejected; review remaining actions"
                    )
                if order["side"] == "SELL" and order["status"] != "FILLED":
                    sells_waiting = True
            final = self.readback(self.stops.store.get(proposal_id))
            complete = bool(final["broker_orders"]) and all(
                row["status"] == "FILLED" for row in final["broker_orders"]
            )
            with sqlite_connection(self.database) as connection:
                connection.execute(
                    "UPDATE proposal_execution_requests SET status=?,last_error=NULL WHERE proposal_id=?",
                    ("COMPLETE" if complete else "SUBMITTED", proposal_id),
                )
                if complete:
                    version = next(
                        row["version"]
                        for row in self.stops.ledger.accounts()
                        if row["account_id"] == proposal["account_id"]
                    )
                    self.stops.store.mark_processed(
                        connection, proposal_id, version, datetime.now(UTC).isoformat(), []
                    )
            return self.readback(self.stops.store.get(proposal_id))
        except DomainValidationError as exc:
            with sqlite_connection(self.database) as connection:
                connection.execute(
                    "UPDATE proposal_execution_requests SET status='BLOCKED',last_error=? WHERE proposal_id=?",
                    (str(exc), proposal_id),
                )
            return self.readback(self.stops.store.get(proposal_id))

    def tick(self):
        with sqlite_connection(self.database, read_only=True) as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT proposal_id FROM proposal_execution_requests WHERE status IN ('QUEUED','SUBMITTED')"
                )
            ]
        for proposal_id in ids:
            self.process(proposal_id)
