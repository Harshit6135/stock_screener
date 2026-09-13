"""Paper-only broker adapter.  It never performs a network order call."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from src.platform_kernel import DomainValidationError
from src.portfolio_accounting import Fill

from .ledger import Ledger


@dataclass(frozen=True)
class PaperExecutionReport:
    broker_order_id: str
    fill: Fill
    ledger_version: int


class PaperBroker:
    def __init__(self, ledger: Ledger | None = None, account_id: str | None = None):
        self.ledger = ledger
        self.account_id = account_id

    def submit(
        self,
        fill: Fill,
        allow_live: bool = False,
        *,
        idempotency_key: str | None = None,
        expected_version: int | None = None,
    ) -> PaperExecutionReport:
        if allow_live:
            raise DomainValidationError(
                "live broker dispatch is disabled; use an explicitly approved broker adapter"
            )
        if self.ledger is None or not self.account_id:
            raise DomainValidationError("paper broker requires an authoritative ledger account")
        if not idempotency_key or expected_version is None:
            raise DomainValidationError("paper execution requires idempotency and expected version")
        broker_order_id = f"paper-{uuid5(NAMESPACE_URL, f'{self.account_id}:{idempotency_key}')}"
        version = self.ledger.record_fills(
            self.account_id,
            idempotency_key,
            expected_version,
            (fill,),
            order_id=broker_order_id,
        )
        return PaperExecutionReport(broker_order_id, fill, version)
