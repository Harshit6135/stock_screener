"""Reference identity is versioned independently from market bars."""

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Protocol
from uuid import UUID, uuid4

from src.platform_kernel import (
    ArtifactManifest,
    ArtifactStore,
    DomainValidationError,
    QualityStatus,
    freeze_value,
)


@dataclass(frozen=True)
class Instrument:
    instrument_id: UUID
    isin: str
    symbol: str
    exchange: str

    def __post_init__(self) -> None:
        if not self.isin or not self.symbol or not self.exchange:
            raise DomainValidationError("instrument identity fields must be non-empty")


@dataclass(frozen=True)
class InstrumentAlias:
    instrument_id: UUID
    alias: str
    exchange: str
    effective_from: date
    effective_to: date | None = None
    provider_token: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.alias
            or not self.exchange
            or self.effective_to
            and self.effective_to < self.effective_from
            or self.provider_token is not None
            and not self.provider_token
        ):
            raise DomainValidationError("instrument alias is invalid")


@dataclass(frozen=True)
class UniverseSnapshot:
    snapshot_id: UUID
    as_of_date: date
    instrument_ids: tuple[UUID, ...]
    name: str

    @classmethod
    def create(
        cls, as_of_date: date, instrument_ids: Iterable[UUID], name: str
    ) -> "UniverseSnapshot":
        identifiers = tuple(instrument_ids)
        if not name or not identifiers or len(set(identifiers)) != len(identifiers):
            raise DomainValidationError("universe snapshot is invalid")
        return cls(uuid4(), as_of_date, identifiers, name)

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        return store.publish_json(
            "reference/universes",
            str(self.snapshot_id),
            {
                "snapshot_id": str(self.snapshot_id),
                "as_of_date": self.as_of_date,
                "name": self.name,
                "instrument_ids": [str(value) for value in self.instrument_ids],
            },
        )


class UniverseExclusionReason(str, Enum):
    """A stable explanation for why an equity cannot enter the universe."""

    MISSING_BAR = "missing_bar"
    INSUFFICIENT_HISTORY = "insufficient_history"
    LOW_TURNOVER = "low_turnover"
    ZERO_VOLUME = "zero_volume"
    FLAT_OHLC = "flat_ohlc"
    LOW_PRICE = "low_price"


class LiquidityBar(Protocol):
    """The completed equity-bar shape required by the liquidity policy."""

    @property
    def instrument_id(self) -> str: ...

    @property
    def as_of_date(self) -> date: ...

    @property
    def open(self) -> Decimal: ...

    @property
    def high(self) -> Decimal: ...

    @property
    def low(self) -> Decimal: ...

    @property
    def close(self) -> Decimal: ...

    @property
    def volume(self) -> int: ...

    @property
    def traded_value(self) -> Decimal | None: ...


@dataclass(frozen=True)
class LiquidityUniversePolicy:
    """Versioned, point-in-time rules for a tradable equity universe.

    `close * volume` is intentionally named a proxy. A provider carrying an
    exchange-reported traded value can be adapted at ingestion time without
    changing how eligibility or its audit record is evaluated.
    """

    policy_id: UUID
    name: str
    lookback_sessions: int
    minimum_valid_sessions: int
    minimum_median_daily_turnover: Decimal
    minimum_price: Decimal | None = None

    def __post_init__(self) -> None:
        minimum_turnover = Decimal(str(self.minimum_median_daily_turnover))
        minimum_price = Decimal(str(self.minimum_price)) if self.minimum_price is not None else None
        if (
            not self.name.strip()
            or self.lookback_sessions <= 0
            or self.minimum_valid_sessions <= 0
            or self.minimum_valid_sessions > self.lookback_sessions
            or not minimum_turnover.is_finite()
            or minimum_turnover < 0
            or minimum_price is not None
            and (not minimum_price.is_finite() or minimum_price <= 0)
        ):
            raise DomainValidationError("liquidity universe policy is invalid")
        object.__setattr__(self, "minimum_median_daily_turnover", minimum_turnover)
        object.__setattr__(self, "minimum_price", minimum_price)


@dataclass(frozen=True)
class LiquidityUniverseMember:
    instrument_id: UUID
    eligible: bool
    exclusion_reasons: tuple[UniverseExclusionReason, ...]
    valid_sessions: int
    median_daily_turnover: Decimal | None
    latest_close: Decimal | None
    flat_ohlc: bool

    def __post_init__(self) -> None:
        median = (
            Decimal(str(self.median_daily_turnover))
            if self.median_daily_turnover is not None
            else None
        )
        latest_close = Decimal(str(self.latest_close)) if self.latest_close is not None else None
        if (
            self.valid_sessions < 0
            or len(set(self.exclusion_reasons)) != len(self.exclusion_reasons)
            or self.eligible != (not self.exclusion_reasons)
            or median is not None
            and (not median.is_finite() or median < 0)
            or latest_close is not None
            and (not latest_close.is_finite() or latest_close <= 0)
        ):
            raise DomainValidationError("liquidity universe member is invalid")
        object.__setattr__(self, "median_daily_turnover", median)
        object.__setattr__(self, "latest_close", latest_close)


@dataclass(frozen=True)
class LiquidityUniverseSnapshot:
    snapshot_id: UUID
    as_of_date: date
    policy: LiquidityUniversePolicy
    turnover_basis: str
    members: tuple[LiquidityUniverseMember, ...]

    def __post_init__(self) -> None:
        if (
            not self.turnover_basis.strip()
            or not self.members
            or len({member.instrument_id for member in self.members}) != len(self.members)
            or tuple(sorted(self.members, key=lambda member: str(member.instrument_id)))
            != self.members
        ):
            raise DomainValidationError("liquidity universe snapshot is invalid")

    @property
    def instrument_ids(self) -> tuple[UUID, ...]:
        return tuple(member.instrument_id for member in self.members if member.eligible)

    def to_payload(self) -> dict[str, object]:
        return {
            "snapshot_id": str(self.snapshot_id),
            "as_of_date": self.as_of_date,
            "policy": asdict(self.policy),
            "turnover_basis": self.turnover_basis,
            "members": [
                {
                    "instrument_id": str(member.instrument_id),
                    "eligible": member.eligible,
                    "exclusion_reasons": [reason.value for reason in member.exclusion_reasons],
                    "valid_sessions": member.valid_sessions,
                    "median_daily_turnover": member.median_daily_turnover,
                    "latest_close": member.latest_close,
                    "flat_ohlc": member.flat_ohlc,
                }
                for member in self.members
            ],
        }

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        return store.publish_json(
            "reference/liquidity_universes",
            str(self.snapshot_id),
            self.to_payload(),
        )


def build_liquidity_universe(
    instruments: Iterable[Instrument],
    bars: Iterable[LiquidityBar],
    as_of_date: date,
    policy: LiquidityUniversePolicy,
) -> LiquidityUniverseSnapshot:
    """Build an auditable equity universe using only completed bars at `as_of_date`.

    The protocol deliberately avoids coupling reference identity to the
    market-data package. `NormalizedBar` satisfies this shape.
    """
    instrument_records = tuple(instruments)
    instruments_by_id = {
        str(instrument.instrument_id): instrument for instrument in instrument_records
    }
    if not instruments_by_id:
        raise DomainValidationError("liquidity universe requires at least one instrument")
    if len(instruments_by_id) != len(instrument_records):
        raise DomainValidationError("liquidity universe contains duplicate instruments")

    bars_by_instrument: dict[str, list[LiquidityBar]] = {key: [] for key in instruments_by_id}
    for bar in bars:
        instrument_key = str(bar.instrument_id)
        if instrument_key in bars_by_instrument and bar.as_of_date <= as_of_date:
            bars_by_instrument[instrument_key].append(bar)

    for history in bars_by_instrument.values():
        dates = [bar.as_of_date for bar in history]
        if len(dates) != len(set(dates)):
            raise DomainValidationError("liquidity universe contains duplicate instrument dates")

    evaluated_bars = tuple(bar for history in bars_by_instrument.values() for bar in history)
    exact_turnover = tuple(bar.traded_value is not None for bar in evaluated_bars)
    if any(exact_turnover) and not all(exact_turnover):
        raise DomainValidationError("liquidity universe must not mix turnover bases")
    turnover_basis = "reported_traded_value" if any(exact_turnover) else "close_times_volume_proxy"

    members: list[LiquidityUniverseMember] = []
    for instrument_key, instrument in instruments_by_id.items():
        history = sorted(bars_by_instrument[instrument_key], key=lambda bar: bar.as_of_date)
        latest = next((bar for bar in reversed(history) if bar.as_of_date == as_of_date), None)
        reasons: list[UniverseExclusionReason] = []
        if latest is None:
            reasons.append(UniverseExclusionReason.MISSING_BAR)
        else:
            volume = latest.volume
            if volume == 0:
                reasons.append(UniverseExclusionReason.ZERO_VOLUME)
            elif _is_flat_ohlc(latest):
                reasons.append(UniverseExclusionReason.FLAT_OHLC)
            if policy.minimum_price is not None and latest.close < policy.minimum_price:
                reasons.append(UniverseExclusionReason.LOW_PRICE)

        trailing = history[-policy.lookback_sessions :]
        valid_sessions = len(trailing)
        median_turnover = (
            _median(
                [
                    bar.traded_value if bar.traded_value is not None else bar.close * bar.volume
                    for bar in trailing
                ]
            )
            if trailing
            else None
        )
        if valid_sessions < policy.minimum_valid_sessions:
            reasons.append(UniverseExclusionReason.INSUFFICIENT_HISTORY)
        elif median_turnover is not None and median_turnover < policy.minimum_median_daily_turnover:
            reasons.append(UniverseExclusionReason.LOW_TURNOVER)
        members.append(
            LiquidityUniverseMember(
                instrument.instrument_id,
                not reasons,
                tuple(reasons),
                valid_sessions,
                median_turnover,
                latest.close if latest is not None else None,
                bool(latest is not None and _is_flat_ohlc(latest)),
            )
        )
    return LiquidityUniverseSnapshot(
        uuid4(),
        as_of_date,
        policy,
        turnover_basis,
        tuple(sorted(members, key=lambda member: str(member.instrument_id))),
    )


def _is_flat_ohlc(bar: LiquidityBar) -> bool:
    prices = (bar.open, bar.high, bar.low, bar.close)
    return len(set(prices)) == 1


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    return (
        ordered[midpoint] if len(ordered) % 2 else (ordered[midpoint - 1] + ordered[midpoint]) / 2
    )


@dataclass(frozen=True)
class CorporateAction:
    instrument_id: UUID
    effective_date: date
    action_type: str
    ratio: str

    def __post_init__(self) -> None:
        if self.action_type not in {"SPLIT", "DIVIDEND", "BONUS"} or not self.ratio:
            raise DomainValidationError("corporate action is invalid")


@dataclass(frozen=True)
class ExchangeCalendar:
    exchange: str
    trading_dates: tuple[date, ...]
    as_of_date: date

    def __post_init__(self) -> None:
        if (
            not self.exchange
            or not self.trading_dates
            or tuple(sorted(self.trading_dates)) != self.trading_dates
            or len(set(self.trading_dates)) != len(self.trading_dates)
        ):
            raise DomainValidationError("exchange calendar is invalid")

    def is_trading_day(self, value: date) -> bool:
        return value in self.trading_dates

    def next_trading_day(self, value: date) -> date | None:
        return next((item for item in self.trading_dates if item > value), None)

    def sessions_between(self, start: date, end: date) -> tuple[date, ...]:
        if end < start:
            raise DomainValidationError("calendar range is invalid")
        return tuple(item for item in self.trading_dates if start <= item <= end)


@dataclass(frozen=True)
class CorporateActionSnapshot:
    snapshot_id: UUID
    as_of_date: date
    actions: tuple[CorporateAction, ...]

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        if not self.actions:
            raise DomainValidationError("corporate action snapshot must not be empty")
        return store.publish_json(
            "reference/corporate_actions",
            str(self.snapshot_id),
            {
                "snapshot_id": str(self.snapshot_id),
                "as_of_date": self.as_of_date,
                "actions": [asdict(action) for action in self.actions],
            },
        )


@dataclass(frozen=True)
class FundamentalSnapshot:
    snapshot_id: UUID
    as_of_date: date
    available_at: date
    values: Mapping[str, Mapping[str, object]]

    def __post_init__(self) -> None:
        if self.available_at < self.as_of_date or not self.values:
            raise DomainValidationError("fundamental snapshot availability is invalid")
        object.__setattr__(self, "values", freeze_value(dict(self.values)))

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        return store.publish_json(
            "reference/fundamentals",
            str(self.snapshot_id),
            {
                "snapshot_id": str(self.snapshot_id),
                "as_of_date": self.as_of_date,
                "available_at": self.available_at,
                "values": dict(self.values),
            },
        )


def publish_alias_snapshot(
    store: ArtifactStore,
    aliases: Iterable[InstrumentAlias],
    as_of_date: date,
) -> ArtifactManifest:
    records = tuple(
        sorted(aliases, key=lambda item: (str(item.instrument_id), item.effective_from))
    )
    if not records:
        raise DomainValidationError("alias snapshot must not be empty")
    snapshot_id = uuid4()
    return store.publish_json(
        "reference/aliases",
        str(snapshot_id),
        {
            "snapshot_id": str(snapshot_id),
            "as_of_date": as_of_date,
            "aliases": [asdict(alias) for alias in records],
        },
    )


def publish_calendar_snapshot(store: ArtifactStore, calendar: ExchangeCalendar) -> ArtifactManifest:
    snapshot_id = uuid4()
    return store.publish_json(
        "reference/calendars",
        str(snapshot_id),
        {"snapshot_id": str(snapshot_id), **asdict(calendar)},
    )


def resolve_alias(
    aliases: Iterable[InstrumentAlias],
    alias: str,
    exchange: str,
    as_of_date: date,
) -> InstrumentAlias:
    matches = tuple(
        item
        for item in aliases
        if item.alias == alias
        and item.exchange == exchange
        and item.effective_from <= as_of_date
        and (item.effective_to is None or as_of_date <= item.effective_to)
    )
    if len(matches) != 1:
        raise DomainValidationError("alias must resolve to exactly one point-in-time instrument")
    return matches[0]


def publish_instrument_snapshot(
    store: ArtifactStore,
    instruments: Iterable[Instrument],
    quality: QualityStatus = QualityStatus.COMPLETE,
) -> ArtifactManifest:
    records = tuple(instruments)
    if not records:
        raise DomainValidationError("instrument snapshot must contain at least one instrument")
    isins = [item.isin for item in records]
    if len(isins) != len(set(isins)):
        raise DomainValidationError("instrument snapshot contains duplicate ISINs")
    snapshot_id = uuid4()
    return store.publish_json(
        category="reference/instruments",
        artifact_id=str(snapshot_id),
        payload={
            "snapshot_id": str(snapshot_id),
            "instruments": [asdict(item) for item in records],
        },
        quality=quality,
    )
