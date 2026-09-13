"""Reference identity is versioned independently from market bars."""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Iterable
from uuid import UUID, uuid4

from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, QualityStatus


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

    def __post_init__(self) -> None:
        if not self.alias or not self.exchange or self.effective_to and self.effective_to < self.effective_from:
            raise DomainValidationError("instrument alias is invalid")


@dataclass(frozen=True)
class UniverseSnapshot:
    snapshot_id: UUID
    as_of_date: date
    instrument_ids: tuple[UUID, ...]
    name: str

    @classmethod
    def create(cls, as_of_date: date, instrument_ids: Iterable[UUID], name: str) -> "UniverseSnapshot":
        identifiers = tuple(instrument_ids)
        if not name or not identifiers or len(set(identifiers)) != len(identifiers):
            raise DomainValidationError("universe snapshot is invalid")
        return cls(uuid4(), as_of_date, identifiers, name)

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        return store.publish_json("reference/universes", str(self.snapshot_id), {"snapshot_id": str(self.snapshot_id), "as_of_date": self.as_of_date, "name": self.name, "instrument_ids": [str(value) for value in self.instrument_ids]})


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
        if not self.exchange or not self.trading_dates or tuple(sorted(self.trading_dates)) != self.trading_dates:
            raise DomainValidationError("exchange calendar is invalid")


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
        payload={"snapshot_id": str(snapshot_id), "instruments": [asdict(item) for item in records]},
        quality=quality,
    )
