"""Paper-only broker adapter.  It never performs a network order call."""

from dataclasses import dataclass
from uuid import uuid4

from src.platform_kernel import DomainValidationError
from src.portfolio_accounting import Fill


@dataclass(frozen=True)
class PaperExecutionReport:
    broker_order_id: str
    fill: Fill


class PaperBroker:
    def submit(self, fill: Fill, allow_live: bool = False) -> PaperExecutionReport:
        if allow_live:
            raise DomainValidationError("live broker dispatch is disabled; use an explicitly approved broker adapter")
        return PaperExecutionReport(f"paper-{uuid4()}", fill)
