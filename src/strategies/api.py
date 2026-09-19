"""Versioned research definitions without indicator or broker dependencies."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from src.platform_kernel import ArtifactManifest, ArtifactStore, DomainValidationError, freeze_value

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class RevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    BACKTESTED = "BACKTESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class PortfolioPolicyRevision:
    policy_id: str
    revision_id: UUID
    max_positions: int
    max_concentration: Decimal
    stop_loss_multiplier: Decimal

    def __post_init__(self) -> None:
        concentration = Decimal(str(self.max_concentration))
        multiplier = Decimal(str(self.stop_loss_multiplier))
        if (
            not self.policy_id
            or self.max_positions < 1
            or not concentration.is_finite()
            or not Decimal(0) < concentration <= Decimal(1)
        ):
            raise DomainValidationError("portfolio policy limits are invalid")
        if not multiplier.is_finite() or multiplier <= 0:
            raise DomainValidationError("stop_loss_multiplier must be positive")
        object.__setattr__(self, "max_concentration", concentration)
        object.__setattr__(self, "stop_loss_multiplier", multiplier)


@dataclass(frozen=True)
class StrategyRevision:
    strategy_id: str
    revision_id: UUID
    semantic_version: str
    policy_revision_id: UUID
    factor_weights: Mapping[str, Decimal]
    feature_configuration_ids: tuple[UUID, ...]
    status: RevisionStatus = RevisionStatus.DRAFT
    factor_directions: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        weights = {name: Decimal(str(weight)) for name, weight in self.factor_weights.items()}
        if (
            not self.strategy_id
            or not _SEMVER.fullmatch(self.semantic_version)
            or not weights
            or any(
                not name or not weight.is_finite() or weight < 0 for name, weight in weights.items()
            )
        ):
            raise DomainValidationError("strategy factor weights are invalid")
        if sum(weights.values()) != Decimal(1):
            raise DomainValidationError("strategy factor weights must sum to one")
        if len(set(self.feature_configuration_ids)) != len(self.feature_configuration_ids):
            raise DomainValidationError("strategy feature configurations must be unique")
        directions = dict(self.factor_directions or {name: "HIGH" for name in weights})
        if set(directions) != set(weights) or any(
            value not in {"HIGH", "LOW"} for value in directions.values()
        ):
            raise DomainValidationError("strategy factor directions are invalid")
        object.__setattr__(self, "factor_weights", freeze_value(weights))
        object.__setattr__(self, "factor_directions", freeze_value(directions))

    @property
    def definition_hash(self) -> str:
        value = json.dumps(
            {
                "strategy_id": self.strategy_id,
                "semantic_version": self.semantic_version,
                "policy_revision_id": str(self.policy_revision_id),
                "factor_weights": {key: str(value) for key, value in self.factor_weights.items()},
                "feature_configuration_ids": [str(item) for item in self.feature_configuration_ids],
                "factor_directions": dict(self.factor_directions or {}),
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class RankingMember:
    instrument_id: str
    score: Decimal
    eligible: bool
    explanation: str
    rank: int = 0
    factor_values: Mapping[str, Decimal] | None = None
    percentile_values: Mapping[str, Decimal] | None = None

    def __post_init__(self) -> None:
        score = Decimal(str(self.score))
        if not self.instrument_id or not score.is_finite() or self.rank < 0:
            raise DomainValidationError("ranking member is invalid")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "factor_values", freeze_value(dict(self.factor_values or {})))
        object.__setattr__(
            self, "percentile_values", freeze_value(dict(self.percentile_values or {}))
        )


@dataclass(frozen=True)
class PercentileSnapshot:
    snapshot_id: UUID
    as_of_date: date
    strategy_revision_id: UUID
    universe_snapshot_id: UUID
    feature_snapshot_ids: tuple[UUID, ...]
    values: Mapping[str, Mapping[str, Decimal]]

    def __post_init__(self) -> None:
        if not self.values or not self.feature_snapshot_ids:
            raise DomainValidationError("percentile snapshot is incomplete")
        object.__setattr__(self, "values", freeze_value(dict(self.values)))

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        return store.publish_json(
            "research/percentiles",
            str(self.snapshot_id),
            {
                "snapshot_id": str(self.snapshot_id),
                "as_of_date": self.as_of_date,
                "strategy_revision_id": str(self.strategy_revision_id),
                "universe_snapshot_id": str(self.universe_snapshot_id),
                "feature_snapshot_ids": [str(item) for item in self.feature_snapshot_ids],
                "values": dict(self.values),
            },
            upstream_ids=tuple(str(item) for item in self.feature_snapshot_ids)
            + (str(self.strategy_revision_id), str(self.universe_snapshot_id)),
        )


@dataclass(frozen=True)
class ScoreSnapshot:
    snapshot_id: UUID
    as_of_date: date
    strategy_revision_id: UUID
    percentile_snapshot_id: UUID
    scores: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not self.scores or any(not value.is_finite() for value in self.scores.values()):
            raise DomainValidationError("score snapshot is invalid")
        object.__setattr__(self, "scores", freeze_value(dict(self.scores)))

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        return store.publish_json(
            "research/scores",
            str(self.snapshot_id),
            {
                "snapshot_id": str(self.snapshot_id),
                "as_of_date": self.as_of_date,
                "strategy_revision_id": str(self.strategy_revision_id),
                "percentile_snapshot_id": str(self.percentile_snapshot_id),
                "scores": dict(self.scores),
            },
            upstream_ids=(str(self.strategy_revision_id), str(self.percentile_snapshot_id)),
        )


@dataclass(frozen=True)
class RankingSnapshot:
    snapshot_id: UUID
    as_of_date: date
    strategy_revision_id: UUID
    score_snapshot_id: UUID
    universe_snapshot_id: UUID
    members: tuple[RankingMember, ...]

    @classmethod
    def create(
        cls,
        as_of_date: date,
        strategy_revision_id: UUID,
        score_snapshot_id: UUID,
        universe_snapshot_id: UUID,
        members: tuple[RankingMember, ...],
    ) -> "RankingSnapshot":
        if not members:
            raise DomainValidationError("ranking snapshot must contain members")
        identifiers = [member.instrument_id for member in members]
        if len(identifiers) != len(set(identifiers)):
            raise DomainValidationError("ranking snapshot has duplicate instruments")
        ordered_members = sorted(
            members, key=lambda item: (not item.eligible, -item.score, item.instrument_id)
        )
        ordered: list[RankingMember] = []
        previous_score: Decimal | None = None
        dense_rank = 0
        for member in ordered_members:
            if member.eligible and member.score != previous_score:
                dense_rank += 1
                previous_score = member.score
            ordered.append(
                RankingMember(
                    member.instrument_id,
                    member.score,
                    member.eligible,
                    member.explanation,
                    dense_rank if member.eligible else 0,
                    member.factor_values,
                    member.percentile_values,
                )
            )
        return cls(
            uuid4(),
            as_of_date,
            strategy_revision_id,
            score_snapshot_id,
            universe_snapshot_id,
            tuple(ordered),
        )

    def publish(self, store: ArtifactStore) -> ArtifactManifest:
        """Publish an immutable ranking with all research inputs in lineage."""
        return store.publish_json(
            "research/rankings",
            str(self.snapshot_id),
            {
                "snapshot_id": str(self.snapshot_id),
                "as_of_date": self.as_of_date,
                "strategy_revision_id": str(self.strategy_revision_id),
                "score_snapshot_id": str(self.score_snapshot_id),
                "universe_snapshot_id": str(self.universe_snapshot_id),
                "members": [
                    {
                        "instrument_id": item.instrument_id,
                        "score": item.score,
                        "eligible": item.eligible,
                        "explanation": item.explanation,
                        "rank": item.rank,
                        "factor_values": item.factor_values or {},
                        "percentile_values": item.percentile_values or {},
                    }
                    for item in self.members
                ],
            },
            upstream_ids=(
                str(self.strategy_revision_id),
                str(self.score_snapshot_id),
                str(self.universe_snapshot_id),
            ),
        )


def build_research_snapshots(
    as_of_date: date,
    strategy: StrategyRevision,
    universe_snapshot_id: UUID,
    features: Mapping[str, Mapping[str, Decimal]],
    feature_snapshot_ids: tuple[UUID, ...],
) -> tuple[PercentileSnapshot, ScoreSnapshot, RankingSnapshot]:
    """Build the explicit percentile, score, and ranking artifact chain."""
    if not features:
        raise DomainValidationError("ranking requires feature values")
    required = set(strategy.factor_weights)
    if not feature_snapshot_ids or len(set(feature_snapshot_ids)) != len(feature_snapshot_ids):
        raise DomainValidationError("feature snapshot lineage is invalid")
    rows = {
        instrument_id: {name: Decimal(str(value)) for name, value in values.items()}
        for instrument_id, values in features.items()
    }
    if any(set(values) != required for values in rows.values()):
        raise DomainValidationError("ranking feature set does not match strategy factors")
    if any(not value.is_finite() for values in rows.values() for value in values.values()):
        raise DomainValidationError("ranking features must be finite")
    percentiles: dict[str, dict[str, Decimal]] = {instrument_id: {} for instrument_id in rows}
    directions = strategy.factor_directions
    if directions is None:  # Normalized in StrategyRevision.__post_init__.
        raise DomainValidationError("strategy factor directions are missing")
    for factor in sorted(required):
        ordered = sorted(
            rows, key=lambda instrument_id: (rows[instrument_id][factor], instrument_id)
        )
        if len(ordered) == 1:
            percentiles[ordered[0]][factor] = Decimal(100)
            continue
        denominator = Decimal(len(ordered) - 1)
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and rows[ordered[end]][factor] == rows[ordered[start]][factor]:
                end += 1
            average_index = (Decimal(start) + Decimal(end - 1)) / Decimal(2)
            percentile = average_index * Decimal(100) / denominator
            if directions[factor] == "LOW":
                percentile = Decimal(100) - percentile
            for instrument_id in ordered[start:end]:
                percentiles[instrument_id][factor] = percentile
            start = end
    percentile_snapshot = PercentileSnapshot(
        uuid4(),
        as_of_date,
        strategy.revision_id,
        universe_snapshot_id,
        feature_snapshot_ids,
        percentiles,
    )
    scores = {
        instrument_id: sum(
            (
                percentiles[instrument_id][factor] * strategy.factor_weights[factor]
                for factor in required
            ),
            start=Decimal(0),
        )
        for instrument_id in rows
    }
    score_snapshot = ScoreSnapshot(
        uuid4(), as_of_date, strategy.revision_id, percentile_snapshot.snapshot_id, scores
    )
    members = tuple(
        RankingMember(
            instrument_id,
            scores[instrument_id],
            True,
            "eligible: complete approved features",
            factor_values=rows[instrument_id],
            percentile_values=percentiles[instrument_id],
        )
        for instrument_id in rows
    )
    ranking = RankingSnapshot.create(
        as_of_date,
        strategy.revision_id,
        score_snapshot.snapshot_id,
        universe_snapshot_id,
        members,
    )
    return percentile_snapshot, score_snapshot, ranking


def rank_feature_values(
    as_of_date: date,
    strategy: StrategyRevision,
    universe_snapshot_id: UUID,
    features: Mapping[str, Mapping[str, Decimal]],
    feature_snapshot_ids: tuple[UUID, ...],
) -> RankingSnapshot:
    """Compatibility helper returning the ranking from the explicit artifact chain."""
    return build_research_snapshots(
        as_of_date, strategy, universe_snapshot_id, features, feature_snapshot_ids
    )[2]
