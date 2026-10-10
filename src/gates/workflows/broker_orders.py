"""Coordinate broker orders across execution, portfolio, market, and risk APIs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from kiteconnect.exceptions import PermissionException

from src.domains.execution import (
    BrokerExecutionGateway,
    BrokerOrderRepository,
    KiteExecutionGateway,
)
from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.domains.portfolio_engine import PortfolioProposalStore
from src.gates.repositories import MarketRepository
from src.platform_kernel import DomainValidationError, Money, Quantity


class BrokerOrderWorkflow:
    def __init__(
        self,
        database: str | Path,
        ledger: Ledger,
        gateway: BrokerExecutionGateway | None = None,
        risk_config=None,
        *,
        repository: BrokerOrderRepository | None = None,
        proposal_store: PortfolioProposalStore | None = None,
        market: MarketRepository | None = None,
    ) -> None:
        self.database = Path(database)
        self.repository = repository or BrokerOrderRepository(self.database)
        self.proposals = proposal_store or PortfolioProposalStore(self.database)
        self.market = market or MarketRepository(self.database)
        self.ledger, self.gateway, self.risk_config = ledger, gateway, risk_config
        self.risk_guard = None

    def execution_controls(self) -> dict[str, object]:
        """Return non-secret execution guard state for operator readback."""
        if self.gateway is None:
            return {"enabled": False, "kill_switch": True, "gateway": "unavailable"}
        controls = getattr(self.gateway, "controls", None)
        if not callable(controls):
            return {"gateway": type(self.gateway).__name__, "controls": "unavailable"}
        return {"gateway": type(self.gateway).__name__, **controls()}

    def create_basket(self, payload: dict[str, object]) -> dict[str, object]:
        required = {"account_id", "proposal_id", "idempotency_key", "execution_mode", "orders"}
        if (
            not isinstance(payload, dict)
            or set(payload) - (required | {"slice_count", "interval_seconds"})
            or not required.issubset(payload)
            or not isinstance(payload["orders"], list)
            or not payload["orders"]
        ):
            raise DomainValidationError("basket intent is incomplete")
        mode = payload["execution_mode"]
        if mode not in {"BASKET", "TWAP", "VWAP"}:
            raise DomainValidationError("basket execution mode is invalid")
        slice_count = payload.get("slice_count", 1 if mode == "BASKET" else 2)
        interval = payload.get("interval_seconds", 0 if mode == "BASKET" else 60)
        if (
            isinstance(slice_count, bool)
            or not isinstance(slice_count, int)
            or not 1 <= slice_count <= 100
            or isinstance(interval, bool)
            or not isinstance(interval, int)
            or not 0 <= interval <= 3600
        ):
            raise DomainValidationError("basket slice policy is invalid")
        if mode == "BASKET" and slice_count != 1:
            raise DomainValidationError("BASKET mode must use one slice")
        account_id, proposal_id, idempotency_key = (
            str(payload[key]) for key in ("account_id", "proposal_id", "idempotency_key")
        )
        if not all(value.strip() for value in (account_id, proposal_id, idempotency_key)):
            raise DomainValidationError("basket identity is invalid")
        basket_id = str(uuid5(NAMESPACE_URL, f"broker-basket:{idempotency_key}"))
        existing = self.repository.existing_basket(idempotency_key)
        if existing is not None:
            return self.basket(str(existing["basket_id"]))
        child_ids: list[str] = []
        for index, order in enumerate(payload["orders"]):
            if not isinstance(order, dict):
                raise DomainValidationError("basket order is invalid")
            child = {
                **order,
                "account_id": account_id,
                "proposal_id": proposal_id,
                "idempotency_key": f"{idempotency_key}:{index}",
            }
            child_ids.append(str(self.create_intent(child)["order_id"]))
        timestamp = datetime.now(UTC).isoformat()
        self.repository.create_basket(
            basket_id=basket_id,
            account_id=account_id,
            proposal_id=proposal_id,
            idempotency_key=idempotency_key,
            execution_mode=str(mode),
            slice_count=slice_count,
            interval_seconds=interval,
            created_at=timestamp,
            child_order_ids=child_ids,
        )
        return self.basket(basket_id)

    def basket(self, basket_id: str) -> dict[str, object]:
        row, children = self.repository.basket(basket_id)
        return {
            **dict(row),
            "orders": [
                {"slice_index": item["slice_index"], "order": self.get(str(item["order_id"]))}
                for item in children
            ],
        }

    def submit_basket(self, basket_id: str, slice_index: int = 0) -> dict[str, object]:
        basket = self.basket(basket_id)
        if isinstance(slice_index, bool) or not isinstance(slice_index, int) or slice_index < 0:
            raise DomainValidationError("basket slice index is invalid")
        selected = [item for item in basket["orders"] if item["slice_index"] == slice_index]
        if not selected:
            raise DomainValidationError("basket slice was not found")
        submitted = [self.submit(str(item["order"]["order_id"])) for item in selected]
        return {
            "basket_id": basket_id,
            "execution_mode": basket["execution_mode"],
            "slice_index": slice_index,
            "orders": submitted,
        }

    def create_intent(self, payload: dict[str, object]) -> dict[str, object]:
        required = {
            "account_id",
            "proposal_id",
            "idempotency_key",
            "instrument_id",
            "symbol",
            "exchange",
            "side",
            "quantity",
            "order_type",
        }
        optional = {
            "variety",
            "broker_account_id",
            "strategy_id",
            "decision_date",
            "target_session_date",
            "exit_reason",
            "expected_ledger_version",
        }
        if (
            not isinstance(payload, dict)
            or not required.issubset(payload)
            or set(payload) - (required | optional)
        ):
            raise DomainValidationError("broker order intent is incomplete")
        if (
            payload["side"] not in {"BUY", "SELL"}
            or payload["exchange"] != "NSE"
            or payload["order_type"] not in {"MARKET", "LIMIT"}
        ):
            raise DomainValidationError("broker order intent values are invalid")
        variety = str(payload.get("variety", "regular"))
        if variety not in {"regular", "amo"}:
            raise DomainValidationError("broker order variety is invalid")
        if variety == "amo" and payload["side"] != "SELL":
            raise DomainValidationError("AMO is only supported for next-session SELL intents")
        if (
            isinstance(payload["quantity"], bool)
            or not isinstance(payload["quantity"], int)
            or payload["quantity"] < 1
        ):
            raise DomainValidationError("broker order quantity is invalid")
        if not all(
            isinstance(payload[field], str) and str(payload[field]).strip()
            for field in ("account_id", "proposal_id", "idempotency_key", "instrument_id", "symbol")
        ):
            raise DomainValidationError("broker order identity is invalid")
        order_id = str(uuid4())
        timestamp = datetime.now(UTC).isoformat()
        return self.repository.create_intent(
            order_id=order_id,
            payload=payload,
            variety=variety,
            created_at=timestamp,
        )

    def get(self, order_id: str) -> dict[str, object]:
        return self.repository.get(order_id)

    def prepare_proposal(
        self, proposal_id: str, *, regular_session=False
    ) -> list[dict[str, object]]:
        """Create local intents only. Submission remains an explicit gated command."""
        if self.risk_guard is None:
            raise DomainValidationError("managed portfolio guards are unavailable")
        try:
            proposal = self.proposals.get(proposal_id)
        except DomainValidationError as exc:
            raise DomainValidationError("an approved proposal is required") from exc
        if proposal["status"] != "APPROVED":
            raise DomainValidationError("an approved proposal is required")
        accounts = getattr(self.gateway, "accounts", None)
        if accounts is None:
            raise DomainValidationError("account-specific broker routing is unavailable")
        binding = accounts.binding(proposal["account_id"])
        decisions = [
            decision
            for decision, state in zip(
                proposal["decisions"], proposal["decision_statuses"], strict=True
            )
            if state == "APPROVED"
        ]
        if not decisions:
            raise DomainValidationError("approved proposal stocks are required")
        self.risk_guard.validate(
            proposal["account_id"],
            decisions,
            int(proposal["expected_ledger_version"]),
            reservation_id=f"proposal:{proposal_id}",
            proposal_id=proposal_id,
        )
        results = []
        for index, decision in enumerate(decisions):
            if decision["type"] == "NO_ACTION":
                continue
            instrument = self.market.instrument_by_id(decision["instrument_id"])
            if instrument is None:
                raise DomainValidationError("proposal instrument identity is unavailable")
            side = "BUY" if decision["type"] in {"BUY", "PYRAMID_ADD"} else "SELL"
            protective = decision["type"] in {"HARD_STOP", "STOP_LOSS"}
            variety = (
                "amo"
                if side == "SELL"
                and not protective
                and proposal["strategy_id"] != "manual"
                and not regular_session
                else "regular"
            )
            order = self.create_intent(
                {
                    "account_id": proposal["account_id"],
                    "proposal_id": proposal_id,
                    "idempotency_key": f"proposal:{proposal_id}:decision:{index}",
                    "instrument_id": decision["instrument_id"],
                    "symbol": instrument["symbol"],
                    "exchange": "NSE",
                    "side": side,
                    "quantity": int(decision["units"]),
                    "order_type": "MARKET",
                    "variety": variety,
                    "broker_account_id": binding["broker_account_id"],
                    "strategy_id": binding["strategy_id"],
                    "decision_date": proposal["ranking_week_end"],
                    "target_session_date": proposal["action_date"],
                    "exit_reason": decision.get("exit_reason") or decision["type"].lower(),
                    "expected_ledger_version": str(proposal["expected_ledger_version"]),
                }
            )
            results.append(self.get(order["order_id"]))
        return results

    def _assert_current_buy_membership(self, order: dict[str, object]) -> None:
        if order["side"] != "BUY":
            return
        snapshot = self.market.latest_universe_snapshot("NIFTY 500")
        identity = self.market.instrument_by_id(str(order["instrument_id"]))
        if snapshot is None or identity is None or identity["exchange"] != "NSE":
            raise DomainValidationError("broker BUY requires a current NSE snapshot member")
        member_isins = {
            str(row["isin"])
            for row in self.market.universe_snapshot_members(
                str(snapshot["snapshot_id"]), limit=1000
            )
        }
        if str(identity["isin"]) not in member_isins:
            raise DomainValidationError("broker BUY stock is outside the current NSE snapshot")

    def submit(self, order_id: str) -> dict[str, object]:
        order = self.get(order_id)
        if order["status"] == "SUBMITTED":
            return order
        if order["status"] != "LOCAL_CREATED":
            raise DomainValidationError("broker order is not submit-ready")
        if self.gateway is None:
            raise DomainValidationError("broker execution gateway is unavailable")
        self._assert_current_buy_membership(order)
        if self.risk_guard:
            try:
                proposal = self.proposals.get(str(order["proposal_id"]))
            except DomainValidationError as exc:
                raise DomainValidationError(
                    "broker order requires an approved owning proposal"
                ) from exc
            if proposal["account_id"] != order["account_id"] or proposal["status"] != "APPROVED":
                raise DomainValidationError("broker order requires an approved owning proposal")
            decisions = [
                item
                for item, state in zip(
                    proposal["decisions"], proposal["decision_statuses"], strict=True
                )
                if state == "APPROVED"
            ]
            decision = next(
                (
                    item
                    for item in decisions
                    if item.get("instrument_id") == order["instrument_id"]
                    and (item.get("type") in {"BUY", "PYRAMID_ADD"}) == (order["side"] == "BUY")
                ),
                None,
            )
            if not decision or int(order["quantity"]) > int(decision["units"]):
                raise DomainValidationError("broker order does not match the approved decision")
            self.risk_guard.validate(
                str(order["account_id"]),
                [{**decision, "units": order["quantity"]}],
                int(proposal["expected_ledger_version"]),
                reservation_id=f"broker:{order_id}",
                proposal_id=str(order["proposal_id"]),
            )
        self.repository.claim_submission(order_id, datetime.now(UTC).isoformat())
        try:
            broker_id = self.gateway.submit_order(order)
        except DomainValidationError:
            self.repository.reset_local_created(order_id)
            if self.risk_guard:
                self.risk_guard.release(f"broker:{order_id}")
            raise
        except PermissionException as exc:
            self.repository.reset_local_created(order_id)
            if self.risk_guard:
                self.risk_guard.release(f"broker:{order_id}")
            reason = str(exc)
            if "no ips configured" in reason.lower() or "static-ip" in reason.lower():
                raise DomainValidationError(
                    f"Kite denied order permission: {reason}. In the Kite developer console, "
                    "open Profile > IP Whitelist and add the static public IP used by this "
                    "app's internet connection. Reconnecting alone will not fix this error."
                ) from exc
            raise DomainValidationError(
                f"Kite denied order permission: {exc}. Check the portfolio Kite app's "
                "order permissions and reconnect the portfolio account before retrying."
            ) from exc
        except Exception as exc:
            self.repository.mark_submit_unknown(
                order_id, type(exc).__name__, datetime.now(UTC).isoformat()
            )
            raise DomainValidationError(
                "broker submission outcome is unknown; reconcile before retry"
            ) from exc
        self.repository.mark_submitted(order_id, broker_id, datetime.now(UTC).isoformat())
        return self.get(order_id)

    def reconcile(self, order_id: str) -> dict[str, object]:
        order = self.get(order_id)
        if order["status"] in {"SUBMITTING", "SUBMIT_UNKNOWN"}:
            lookup = getattr(self.gateway, "find_order", None)
            if not callable(lookup):
                raise DomainValidationError(
                    "unknown broker receipt requires explicit operator review"
                )
            broker_id = lookup(order)
            if not broker_id:
                if self.repository.recover_permission_denial(
                    order_id, datetime.now(UTC).isoformat()
                ):
                    if self.risk_guard:
                        self.risk_guard.release(f"broker:{order_id}")
                    return self.get(order_id)
                raise DomainValidationError(
                    "broker has no confirmed matching receipt; do not resubmit"
                )
            self.repository.recover_receipt(order_id, broker_id, datetime.now(UTC).isoformat())
            order = self.get(order_id)
        if (
            order["status"] not in {"SUBMITTED", "PARTIALLY_FILLED", "FILLED"}
            or not order["broker_order_id"]
        ):
            raise DomainValidationError("broker order is not open for reconciliation")
        if self.gateway is None:
            raise DomainValidationError("broker execution gateway is unavailable")
        if isinstance(self.gateway, KiteExecutionGateway):
            state = self.gateway.order_status(
                str(order["broker_order_id"]), str(order["account_id"])
            )
        else:
            state = self.gateway.order_status(str(order["broker_order_id"]))
        fills = state.get("fills", [])
        if not isinstance(fills, list):
            raise DomainValidationError("broker status has invalid fills")
        for item in fills:
            if not isinstance(item, dict) or not item.get("trade_id"):
                raise DomainValidationError("broker fill is missing trade id")
            self._post_fill_once(order, item)
        status = str(state.get("status", order["status"]))
        posted_units = self.repository.fill_quantity(order_id)
        mapped = (
            "PARTIALLY_FILLED"
            if status in {"OPEN", "PARTIAL"}
            else "FILLED"
            if posted_units == int(order["quantity"])
            else "PARTIALLY_FILLED"
            if posted_units
            else "SUBMITTED"
            if status == "COMPLETE"
            else status
        )
        self.repository.update_status(order_id, mapped, state, datetime.now(UTC).isoformat())
        if self.risk_guard and mapped in {"FILLED", "CANCELLED", "REJECTED"}:
            self.risk_guard.release(f"broker:{order_id}")
            if not self.repository.outstanding_order_count(str(order["proposal_id"])):
                self.risk_guard.release(f"proposal:{order['proposal_id']}")
        return self.get(order_id)

    def manual_fill(self, order_id: str, payload: dict[str, object]) -> dict[str, object]:
        order = self.get(order_id)
        if order["status"] not in {"LOCAL_CREATED", "SUBMIT_UNKNOWN"}:
            raise DomainValidationError("manual fill is allowed only for an unresolved local order")
        if (
            not isinstance(payload, dict)
            or set(payload) != {"quantity", "price", "fill_date", "reason"}
            or not isinstance(payload["reason"], str)
            or not str(payload["reason"]).strip()
        ):
            raise DomainValidationError("manual fill requires quantity, price, date and reason")
        if (
            isinstance(payload["quantity"], bool)
            or not isinstance(payload["quantity"], int)
            or payload["quantity"] < 1
        ):
            raise DomainValidationError("manual fill quantity is invalid")
        try:
            Decimal(str(payload["price"]))
            date.fromisoformat(str(payload["fill_date"]))
        except (ValueError, ArithmeticError) as exc:
            raise DomainValidationError("manual fill price or date is invalid") from exc
        fill = {
            "trade_id": f"MANUAL:{order_id}",
            "quantity": payload["quantity"],
            "price": payload["price"],
            "fill_date": payload["fill_date"],
            "manual_reason": payload["reason"],
        }
        self._post_fill_once(order, fill, manual=True)
        self.repository.mark_manual_filled(order_id)
        return self.get(order_id)

    def _post_fill_once(
        self, order: dict[str, object], item: dict[str, object], manual: bool = False
    ) -> None:
        trade_id = str(item["trade_id"])
        if self.repository.has_fill_event(str(order["order_id"]), trade_id):
            return
        if self.repository.fill_quantity(str(order["order_id"])) + int(str(item["quantity"])) > int(
            str(order["quantity"])
        ):
            raise DomainValidationError("broker trade quantity exceeds the order quantity")
        executed_at = None
        if item.get("executed_at"):
            executed_at = datetime.fromisoformat(str(item["executed_at"]))
            if executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        account = next(
            item for item in self.ledger.accounts() if item["account_id"] == order["account_id"]
        )
        self.ledger.record_fills(
            str(order["account_id"]),
            f"broker-fill:{trade_id}",
            int(str(account["version"])),
            [
                Fill(
                    instrument_id=str(order["instrument_id"]),
                    fill_date=date.fromisoformat(str(item["fill_date"])),
                    side=FillSide(str(order["side"])),
                    units=Quantity(int(str(item["quantity"]))),
                    price=Money(Decimal(str(item["price"]))),
                    broker_trade_id=trade_id,
                    executed_at=executed_at,
                )
            ],
            order_id=str(order["order_id"]),
        )
        self.repository.record_fill_event(
            str(order["order_id"]),
            trade_id,
            "MANUAL_FILL" if manual else "BROKER_FILL",
            item,
            datetime.now(UTC).isoformat(),
        )
