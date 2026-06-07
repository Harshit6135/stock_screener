"""
Action result dataclasses (P5).

Typed return values for buy_action() and sell_action() replacing plain dicts.
Repositories accept these directly via the shared _to_mapping() helper.
"""

import dataclasses
from dataclasses import dataclass, field
from datetime import date


def _to_mapping(obj) -> dict:
    """
    Normalise an action object to a plain dict for SQLAlchemy inserts.

    Accepts:
        - BuyActionResult / SellActionResult dataclasses
        - Plain dicts (pass-through, for callers that still build dicts)
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return dict(obj)


@dataclass
class BuyActionResult:
    """
    Output of ActionGenerator.buy_action().

    All fields map 1-to-1 with ActionsModel columns.
    execution_price is set later by ActionLifecycle during approval.
    """

    action_date: date
    symbol: str
    reason: str
    prev_close: float
    units: int = 0
    capital: float = 0.0
    risk: float = 0.0
    atr: float = 0.0
    stop_loss: float = 0.0
    hard_sl_price: float = 0.0
    execution_price: float = 0.0
    type: str = field(default="buy", init=False)
    status: str = field(default="Pending", init=False)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class SellActionResult:
    """
    Output of ActionGenerator.sell_action().

    All fields map 1-to-1 with ActionsModel columns.
    """

    action_date: date
    symbol: str
    reason: str
    units: int
    prev_close: float
    capital: float
    execution_price: float = 0.0
    type: str = field(default="sell", init=False)
    status: str = field(default="Pending", init=False)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class HoldingResult:
    """
    Typed representation of a portfolio holding row produced by ActionProcessor.

    Fields map 1-to-1 with InvestmentsHoldingsModel columns.
    Use .to_dict() when calling InvestmentRepository.upsert_holdings() or
    InvestmentService.get_summary(), which both accept plain dicts.
    """

    symbol: str
    date: date
    entry_date: date
    entry_price: float
    avg_price: float
    units: int
    atr: float
    score: float
    entry_sl: float
    current_price: float
    current_sl: float

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

