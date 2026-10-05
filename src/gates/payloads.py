"""Typed payload dataclasses for durable job handlers.

Each handler's ``dict[str, Any]`` payload is parsed into a frozen dataclass at
the boundary.  Invalid or missing fields fail immediately with a
``DomainValidationError`` instead of producing a ``KeyError`` deep inside the
handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from src.platform_kernel import DomainValidationError


@dataclass(frozen=True)
class RebuildRangePayload:
    """Payload for ``research.rebuild-range``."""

    start_date: date
    end_date: date
    strategies: tuple[str, ...]
    trading_dates: tuple[date, ...]
    universe_snapshot_id: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RebuildRangePayload:
        allowed = {"start_date", "end_date", "strategies", "trading_dates"}
        if (
            not isinstance(raw, dict)
            or not allowed.issubset(raw)
            or set(raw) - (allowed | {"universe_snapshot_id"})
        ):
            raise DomainValidationError("research range rebuild payload is incomplete")
        try:
            start = date.fromisoformat(str(raw["start_date"]))
            end = date.fromisoformat(str(raw["end_date"]))
            strategies = tuple(str(s) for s in raw["strategies"])
            trading_dates = tuple(date.fromisoformat(str(d)) for d in raw["trading_dates"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("research range dates must be ISO dates") from exc
        return cls(start, end, strategies, trading_dates, raw.get("universe_snapshot_id"))

    def validate(self, available_strategies: tuple[str, ...]) -> None:
        """Raise if the payload contents violate business rules."""
        if (
            self.start_date > self.end_date
            or not self.trading_dates
            or self.trading_dates != tuple(sorted(set(self.trading_dates)))
            or any(d < self.start_date or d > self.end_date for d in self.trading_dates)
            or not self.strategies
            or len(self.strategies) != len(set(self.strategies))
            or any(s not in available_strategies for s in self.strategies)
        ):
            raise DomainValidationError("research range or strategy selection is invalid")


@dataclass(frozen=True)
class RebuildIndicatorsPayload:
    """Payload for ``research.rebuild-indicators``."""

    start_date: date
    end_date: date
    strategies: tuple[str, ...]

    @classmethod
    def from_dict(
        cls, raw: dict[str, Any], default_strategies: tuple[str, ...] = ()
    ) -> RebuildIndicatorsPayload:
        if not isinstance(raw, dict) or set(raw) - {"start_date", "end_date", "strategies"}:
            raise DomainValidationError("indicator rebuild payload is invalid")
        if "start_date" not in raw or "end_date" not in raw:
            raise DomainValidationError("indicator rebuild requires start_date and end_date")
        try:
            start = date.fromisoformat(str(raw["start_date"]))
            end = date.fromisoformat(str(raw["end_date"]))
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("indicator rebuild dates must be ISO dates") from exc
        strategies = tuple(
            str(s)
            for s in raw.get(
                "strategies",
                default_strategies,
            )
        )
        return cls(start, end, strategies)


@dataclass(frozen=True)
class FetchBarsPayload:
    """Payload for ``market.fetch-kite-bars``."""

    instrument_id: str
    start_date: date
    end_date: date

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FetchBarsPayload:
        required = {"instrument_id", "start_date", "end_date"}
        if not isinstance(raw, dict) or not required.issubset(raw):
            raise DomainValidationError("fetch bars payload is incomplete")
        try:
            return cls(
                instrument_id=str(raw["instrument_id"]),
                start_date=date.fromisoformat(str(raw["start_date"])),
                end_date=date.fromisoformat(str(raw["end_date"])),
            )
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("fetch bars dates must be ISO dates") from exc


@dataclass(frozen=True)
class BacktestPayload:
    """Payload for ``backtest.run``."""

    strategy_id: str
    start_date: date
    end_date: date
    initial_capital: float
    pyramiding: bool

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BacktestPayload:
        required = {"strategy_id", "start_date", "end_date"}
        if not isinstance(raw, dict) or not required.issubset(raw):
            raise DomainValidationError("backtest payload is incomplete")
        try:
            return cls(
                strategy_id=str(raw["strategy_id"]),
                start_date=date.fromisoformat(str(raw["start_date"])),
                end_date=date.fromisoformat(str(raw["end_date"])),
                initial_capital=float(raw.get("initial_capital", 200_000)),
                pyramiding=bool(raw.get("pyramiding", False)),
            )
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("backtest payload values are invalid") from exc


@dataclass(frozen=True)
class RebuildMultiYearPayload:
    """Payload for ``research.rebuild-multi-year``."""

    start_date: date
    end_date: date
    strategies: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RebuildMultiYearPayload:
        required = {"start_date", "end_date", "strategies"}
        if not isinstance(raw, dict) or not required.issubset(raw):
            raise DomainValidationError("multi-year rebuild payload is incomplete")
        try:
            return cls(
                start_date=date.fromisoformat(str(raw["start_date"])),
                end_date=date.fromisoformat(str(raw["end_date"])),
                strategies=tuple(str(s) for s in raw["strategies"]),
            )
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("multi-year rebuild dates must be ISO dates") from exc

    def validate(self, available_strategies: tuple[str, ...]) -> None:
        """Raise if the payload violates business rules."""
        if self.start_date > self.end_date:
            raise DomainValidationError("start_date must be before end_date")
        if not self.strategies or any(s not in available_strategies for s in self.strategies):
            raise DomainValidationError("multi-year strategies are invalid")
