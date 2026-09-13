"""Pure FIFO accounting; persistence is owned by a later ledger adapter."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Iterable

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


def project(opening_cash: Money, fills: Iterable[Fill]) -> PortfolioProjection:
    """Project cash, open lots, and realised P&L from chronological FIFO fills."""
    cash = opening_cash.amount
    realised = Decimal("0")
    lots: dict[str, list[Lot]] = {}

    for fill in fills:
        value = fill.price.amount * fill.units.units
        if fill.side == FillSide.BUY:
            if value > cash:
                raise DomainValidationError("buy fill exceeds confirmed cash")
            cash -= value
            lots.setdefault(fill.instrument_id, []).append(
                Lot(fill.instrument_id, fill.fill_date, fill.units, fill.price)
            )
            continue

        remaining = fill.units.units
        instrument_lots = lots.get(fill.instrument_id, [])
        available = sum(lot.remaining_units.units for lot in instrument_lots)
        if remaining > available:
            raise DomainValidationError("sell fill exceeds held units")
        cash += value
        rewritten: list[Lot] = []
        for lot in instrument_lots:
            matched = min(remaining, lot.remaining_units.units)
            realised += (fill.price.amount - lot.unit_cost.amount) * matched
            remaining -= matched
            remaining_units = lot.remaining_units.units - matched
            if remaining_units:
                rewritten.append(Lot(lot.instrument_id, lot.opened_on, Quantity(remaining_units), lot.unit_cost))
        lots[fill.instrument_id] = rewritten

    open_lots = tuple(lot for instrument_lots in lots.values() for lot in instrument_lots)
    return PortfolioProjection(Money(cash), open_lots, Money(realised))
