"""Pure FIFO accounting; persistence is owned by a later ledger adapter."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Union

from src.platform_kernel import DomainValidationError, Money, Quantity


class FillSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Fill:
    instrument_id: str
    fill_date: date
    side: FillSide
    units: Quantity
    price: Money
    fee: Money = field(default_factory=lambda: Money(Decimal(0)))
    executed_at: datetime | None = None
    correlation_id: str | None = None
    broker_trade_id: str | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id or self.price.amount <= 0 or self.fee.amount < 0:
            raise DomainValidationError("fill is invalid")
        if self.price.currency != self.fee.currency:
            raise DomainValidationError("fill price and fee currencies must match")
        if self.executed_at is not None and (
            self.executed_at.tzinfo is None or self.executed_at.utcoffset() is None
        ):
            raise DomainValidationError("fill execution timestamp must be timezone-aware")
        if self.executed_at is None:
            object.__setattr__(
                self,
                "executed_at",
                datetime.combine(self.fill_date, datetime.min.time(), tzinfo=UTC),
            )

@dataclass(frozen=True)
class OpeningPosition:
    instrument_id: str
    acquisition_date: date
    units: Quantity
    unit_cost: Money
    imported_at: datetime
    broker_provenance: str

    def __post_init__(self) -> None:
        if not self.instrument_id or self.units.units <= 0 or self.unit_cost.amount <= 0:
            raise DomainValidationError("opening position is invalid")
        if self.imported_at.tzinfo is None or self.imported_at.utcoffset() is None:
            raise DomainValidationError("import timestamp must be timezone-aware")

AccountingEvent = Union[Fill, OpeningPosition]

@dataclass(frozen=True)
class Lot:
    instrument_id: str
    opened_on: date
    remaining_units: Quantity
    unit_cost: Money


@dataclass(frozen=True)
class PortfolioProjection:
    cash: Money
    open_lots: tuple[Lot, ...]
    realised_pnl: Money


def project(opening_cash: Money, events: Iterable[AccountingEvent]) -> PortfolioProjection:
    """Project cash, open lots, and realised P&L from chronological FIFO events."""
    cash = opening_cash.amount
    realised = Decimal(0)
    lots: dict[str, list[Lot]] = {}

    ordered_events = tuple(events)
    
    def event_time(evt: AccountingEvent) -> datetime:
        if isinstance(evt, Fill):
            if evt.executed_at is None:
                raise DomainValidationError("fill execution timestamp is required")
            return evt.executed_at
        return evt.imported_at

    chronology = tuple(event_time(evt) for evt in ordered_events)
    if chronology != tuple(sorted(chronology)):
        raise DomainValidationError("events must be chronological")

    for event in ordered_events:
        if isinstance(event, OpeningPosition):
            if event.unit_cost.currency != opening_cash.currency:
                raise DomainValidationError("opening position currency does not match account currency")
            lots.setdefault(event.instrument_id, []).append(
                Lot(event.instrument_id, event.acquisition_date, event.units, event.unit_cost)
            )
            continue
            
        if event.price.currency != opening_cash.currency:
            raise DomainValidationError("fill currency does not match account currency")
        value = event.price.amount * event.units.units
        if event.side == FillSide.BUY:
            total_cost = value + event.fee.amount
            if total_cost > cash:
                raise DomainValidationError("buy fill exceeds confirmed cash")
            cash -= total_cost
            unit_cost = Money(
                (value + event.fee.amount) / event.units.units,
                event.price.currency,
            )
            lots.setdefault(event.instrument_id, []).append(
                Lot(event.instrument_id, event.fill_date, event.units, unit_cost)
            )
            continue

        remaining = event.units.units
        instrument_lots = lots.get(event.instrument_id, [])
        available = sum(lot.remaining_units.units for lot in instrument_lots)
        if remaining > available:
            raise DomainValidationError("sell fill exceeds held units")
        cash += value - event.fee.amount
        rewritten: list[Lot] = []
        for lot in instrument_lots:
            matched = min(remaining, lot.remaining_units.units)
            allocated_sell_fee = event.fee.amount * Decimal(matched) / Decimal(event.units.units)
            realised += (event.price.amount - lot.unit_cost.amount) * matched - allocated_sell_fee
            remaining -= matched
            remaining_units = lot.remaining_units.units - matched
            if remaining_units:
                rewritten.append(
                    Lot(lot.instrument_id, lot.opened_on, Quantity(remaining_units), lot.unit_cost)
                )
        lots[event.instrument_id] = rewritten

    open_lots = tuple(lot for instrument_lots in lots.values() for lot in instrument_lots)
    return PortfolioProjection(
        Money(cash, opening_cash.currency),
        open_lots,
        Money(realised, opening_cash.currency),
    )
