"""Pure FIFO accounting; persistence is owned by a later ledger adapter."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

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
    realised = Decimal(0)
    lots: dict[str, list[Lot]] = {}

    ordered_fills = tuple(fills)
    if any(fill.executed_at is None for fill in ordered_fills):
        raise DomainValidationError("fill execution timestamp is required")
    chronology = tuple(fill.executed_at for fill in ordered_fills if fill.executed_at is not None)
    if chronology != tuple(sorted(chronology)):
        raise DomainValidationError("fills must be chronological")

    for fill in ordered_fills:
        if fill.price.currency != opening_cash.currency:
            raise DomainValidationError("fill currency does not match account currency")
        value = fill.price.amount * fill.units.units
        if fill.side == FillSide.BUY:
            total_cost = value + fill.fee.amount
            if total_cost > cash:
                raise DomainValidationError("buy fill exceeds confirmed cash")
            cash -= total_cost
            unit_cost = Money(
                (value + fill.fee.amount) / fill.units.units,
                fill.price.currency,
            )
            lots.setdefault(fill.instrument_id, []).append(
                Lot(fill.instrument_id, fill.fill_date, fill.units, unit_cost)
            )
            continue

        remaining = fill.units.units
        instrument_lots = lots.get(fill.instrument_id, [])
        available = sum(lot.remaining_units.units for lot in instrument_lots)
        if remaining > available:
            raise DomainValidationError("sell fill exceeds held units")
        cash += value - fill.fee.amount
        rewritten: list[Lot] = []
        for lot in instrument_lots:
            matched = min(remaining, lot.remaining_units.units)
            allocated_sell_fee = fill.fee.amount * Decimal(matched) / Decimal(fill.units.units)
            realised += (fill.price.amount - lot.unit_cost.amount) * matched - allocated_sell_fee
            remaining -= matched
            remaining_units = lot.remaining_units.units - matched
            if remaining_units:
                rewritten.append(
                    Lot(lot.instrument_id, lot.opened_on, Quantity(remaining_units), lot.unit_cost)
                )
        lots[fill.instrument_id] = rewritten

    open_lots = tuple(lot for instrument_lots in lots.values() for lot in instrument_lots)
    return PortfolioProjection(
        Money(cash, opening_cash.currency),
        open_lots,
        Money(realised, opening_cash.currency),
    )
