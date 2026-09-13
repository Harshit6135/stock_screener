"""Minimal immutable domain contracts for the migration boundary.

These value types deliberately use only the standard library so the core can
be introduced before the framework and persistence cutovers.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, NewType
from uuid import UUID

from .errors import DomainValidationError

AggregateVersion = NewType("AggregateVersion", int)


class FrozenDict(dict):
    """A JSON-compatible mapping that cannot change after construction."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("mapping is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


def freeze_value(value: Any) -> Any:
    """Recursively freeze JSON-like revision and manifest inputs."""
    if isinstance(value, dict):
        return FrozenDict({str(key): freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze_value(item) for item in value)
    return value


def _finite_decimal(value: Decimal | int | float | str, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainValidationError(f"{field_name} must be numeric") from exc
    if not result.is_finite():
        raise DomainValidationError(f"{field_name} must be finite")
    return result


@dataclass(frozen=True)
class Money:
    """A finite non-rounded monetary amount with an explicit currency."""

    amount: Decimal
    currency: str = "INR"

    def __post_init__(self) -> None:
        amount = _finite_decimal(self.amount, "amount")
        if len(self.currency) != 3 or not self.currency.isalpha() or not self.currency.isupper():
            raise DomainValidationError("currency must be a three-letter uppercase code")
        object.__setattr__(self, "amount", amount)


@dataclass(frozen=True)
class Quantity:
    """A positive integer quantity used for lots and order units."""

    units: int

    def __post_init__(self) -> None:
        if isinstance(self.units, bool) or not isinstance(self.units, int) or self.units <= 0:
            raise DomainValidationError("units must be a positive integer")


@dataclass(frozen=True)
class VersionedReference:
    """Stable aggregate ID plus its immutable revision ID."""

    aggregate_id: UUID
    revision_id: UUID


@dataclass(frozen=True)
class CommandMetadata:
    """Concurrency and idempotency metadata required by mutable commands."""

    idempotency_key: UUID
    expected_version: AggregateVersion

    def __post_init__(self) -> None:
        if self.expected_version < 0:
            raise DomainValidationError("expected_version must not be negative")
