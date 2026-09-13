"""Declarative indicator revisions; computation remains an adapter concern."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, freeze_value

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class IndicatorRevision:
    indicator_id: str
    semantic_version: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    parameters: Mapping[str, object]
    warmup_bars: int
    revision_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if (
            not self.indicator_id
            or not _SEMVER.fullmatch(self.semantic_version)
            or not self.inputs
            or not self.outputs
            or len(set(self.inputs)) != len(self.inputs)
            or len(set(self.outputs)) != len(self.outputs)
            or self.warmup_bars < 0
        ):
            raise DomainValidationError("indicator revision is incomplete")
        object.__setattr__(self, "parameters", freeze_value(dict(self.parameters)))

    @property
    def definition_hash(self) -> str:
        body = json.dumps(
            {
                "indicator_id": self.indicator_id,
                "semantic_version": self.semantic_version,
                "inputs": self.inputs,
                "outputs": self.outputs,
                "parameters": dict(self.parameters),
                "warmup_bars": self.warmup_bars,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class IndicatorConfiguration:
    configuration_id: UUID
    revision_id: UUID
    output_alias: str
    parameters: Mapping[str, object]

    @classmethod
    def create(cls, revision: IndicatorRevision, output_alias: str, parameters: Mapping[str, object] | None = None):
        if not output_alias:
            raise DomainValidationError("indicator output alias must be non-empty")
        configured = dict(parameters if parameters is not None else revision.parameters)
        unknown = set(configured) - set(revision.parameters)
        if unknown:
            raise DomainValidationError("indicator configuration contains unknown parameters")
        return cls(uuid4(), revision.revision_id, output_alias, freeze_value(configured))


@dataclass(frozen=True)
class FeatureValue:
    instrument_id: str
    value: Decimal

    def __post_init__(self) -> None:
        value = Decimal(str(self.value))
        if not self.instrument_id or not value.is_finite():
            raise DomainValidationError("feature value is invalid")
        object.__setattr__(self, "value", value)


@dataclass(frozen=True)
class FeatureSnapshot:
    snapshot_id: UUID
    as_of_date: date
    configuration_id: UUID
    values: tuple[FeatureValue, ...]
    market_snapshot_id: UUID

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        if not self.values:
            raise DomainValidationError("feature snapshot must contain values")
        return store.publish_json("features", str(self.snapshot_id), {"snapshot_id": str(self.snapshot_id), "as_of_date": self.as_of_date, "configuration_id": str(self.configuration_id), "market_snapshot_id": str(self.market_snapshot_id), "values": [asdict(value) for value in self.values]}, upstream_ids=(str(self.configuration_id), str(self.market_snapshot_id)))


def compute_feature(configuration: IndicatorConfiguration, revision: IndicatorRevision, market_snapshot_id: UUID, as_of_date: date, closes: Mapping[str, tuple[Decimal, ...]]) -> FeatureSnapshot:
    """Compute only reviewed built-ins; no user-supplied expression is evaluated."""
    if configuration.revision_id != revision.revision_id:
        raise DomainValidationError("indicator configuration does not match its revision")
    if revision.indicator_id not in {"close", "simple_return"}:
        raise DomainValidationError("indicator implementation is not approved")
    output: list[FeatureValue] = []
    for instrument_id, series in sorted(closes.items()):
        values = tuple(Decimal(str(value)) for value in series)
        required = 2 if revision.indicator_id == "simple_return" else 1
        if len(values) < max(required, revision.warmup_bars):
            continue
        if any(not item.is_finite() or item <= 0 for item in values):
            raise DomainValidationError("feature inputs must be positive finite prices")
        value = values[-1] if revision.indicator_id == "close" else (values[-1] / values[-2]) - Decimal("1")
        if not value.is_finite():
            raise DomainValidationError("feature computation produced a non-finite value")
        output.append(FeatureValue(instrument_id, value))
    if not output:
        raise DomainValidationError("insufficient warmup data for feature snapshot")
    return FeatureSnapshot(uuid4(), as_of_date, configuration.configuration_id, tuple(output), market_snapshot_id)
