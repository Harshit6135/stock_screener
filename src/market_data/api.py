"""Normalized bars published separately from provider-specific raw input."""

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Iterable, Mapping
from uuid import UUID, uuid4

from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, QualityStatus


class AdjustmentBasis(str, Enum):
    UNADJUSTED = "UNADJUSTED"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    TOTAL_RETURN_ADJUSTED = "TOTAL_RETURN_ADJUSTED"


@dataclass(frozen=True)
class NormalizedBar:
    instrument_id: str
    as_of_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        prices = [Decimal(str(value)) for value in (self.open, self.high, self.low, self.close)]
        if (
            not self.instrument_id
            or any(not value.is_finite() for value in prices)
            or min(prices) <= 0
            or isinstance(self.volume, bool)
            or not isinstance(self.volume, int)
            or self.volume < 0
        ):
            raise DomainValidationError("bar prices must be positive and volume non-negative")
        if prices[2] > min(prices[0], prices[3]) or prices[1] < max(prices[0], prices[3]):
            raise DomainValidationError("normalized bar OHLC values are inconsistent")
        for name, value in zip(("open", "high", "low", "close"), prices):
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class MarketDataSnapshot:
    snapshot_id: UUID
    provider: str
    bars: tuple[NormalizedBar, ...]
    raw_snapshot_id: UUID | None = None
    adjustment_basis: AdjustmentBasis = AdjustmentBasis.UNADJUSTED

    def __post_init__(self) -> None:
        if not self.provider or not self.bars:
            raise DomainValidationError("market snapshot requires provider and bars")
        keys = [(bar.instrument_id, bar.as_of_date) for bar in self.bars]
        if len(keys) != len(set(keys)):
            raise DomainValidationError("market snapshot contains duplicate instrument dates")
        if keys != sorted(keys):
            raise DomainValidationError("market snapshot bars must be ordered by instrument and date")


def publish_raw_snapshot(
    store: ArtifactStore,
    provider: str,
    payload: Mapping[str, object],
    quality: QualityStatus = QualityStatus.COMPLETE,
) -> ArtifactManifest:
    """Publish provider evidence before normalization or adjustment.

    Raw content is immutable and receives a separate ID so parsing changes can
    be replayed without asking a provider for historical data again.
    """
    if not provider or not payload:
        raise DomainValidationError("raw market snapshot requires provider and payload")
    snapshot_id = uuid4()
    return store.publish_json(
        category=f"market/raw/{provider}",
        artifact_id=str(snapshot_id),
        payload={"snapshot_id": str(snapshot_id), "provider": provider, "payload": dict(payload)},
        quality=quality,
    )


def publish_snapshot(
    store: ArtifactStore,
    provider: str,
    bars: Iterable[NormalizedBar],
    upstream_ids: tuple[str, ...] = (),
    raw_snapshot_id: UUID | None = None,
    quality: QualityStatus = QualityStatus.COMPLETE,
    adjustment_basis: AdjustmentBasis = AdjustmentBasis.UNADJUSTED,
) -> ArtifactManifest:
    ordered_bars = tuple(sorted(bars, key=lambda bar: (bar.instrument_id, bar.as_of_date)))
    snapshot = MarketDataSnapshot(uuid4(), provider, ordered_bars, raw_snapshot_id, adjustment_basis)
    payload = {
        "snapshot_id": str(snapshot.snapshot_id),
        "provider": provider,
        "raw_snapshot_id": str(raw_snapshot_id) if raw_snapshot_id else None,
        "adjustment_basis": adjustment_basis.value,
        "bars": [asdict(bar) for bar in snapshot.bars],
    }
    return store.publish_json(
        category=f"market/normalized/{provider}",
        artifact_id=str(snapshot.snapshot_id),
        payload=payload,
        upstream_ids=upstream_ids + ((str(raw_snapshot_id),) if raw_snapshot_id else ()),
        quality=quality,
    )
