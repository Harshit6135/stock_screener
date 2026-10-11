from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.domains.strategies import (
    RETAINED_STRATEGIES,
    PortfolioPolicyRevision,
    RankingMember,
    RankingSnapshot,
    StrategyRevision,
    rank_feature_values,
)
from src.platform_kernel import DomainValidationError


def test_ranking_ties_are_equal_and_revisions_are_immutable():
    weights = {"close": Decimal(1)}
    strategy = StrategyRevision(
        "tie-safe",
        uuid4(),
        "1.0.0",
        uuid4(),
        weights,
        (uuid4(),),
    )
    original_hash = strategy.definition_hash
    weights["close"] = Decimal(0)
    ranking = rank_feature_values(
        date(2026, 1, 2),
        strategy,
        uuid4(),
        {"A": {"close": Decimal(10)}, "B": {"close": Decimal(10)}},
        (uuid4(),),
    )

    assert strategy.definition_hash == original_hash
    assert {member.percentile_values["close"] for member in ranking.members} == {Decimal(50)}
    assert {member.rank for member in ranking.members} == {1}
    with pytest.raises(TypeError, match="immutable"):
        strategy.factor_weights["close"] = Decimal(0)


def test_strategy_revisions_and_ranking_snapshots_use_strategy_input_ids():
    policy = PortfolioPolicyRevision("momentum-policy", uuid4(), 10, Decimal("0.25"), Decimal(2))
    revision_a = StrategyRevision(
        "momentum",
        uuid4(),
        "1.0.0",
        policy.revision_id,
        {"trend": Decimal(1)},
        (uuid4(),),
    )
    revision_b = StrategyRevision(
        "momentum",
        uuid4(),
        "1.1.0",
        policy.revision_id,
        {"trend": Decimal("0.5"), "momentum": Decimal("0.5")},
        (uuid4(),),
    )
    members = (
        RankingMember("ABC", Decimal(90), True, "eligible"),
        RankingMember("XYZ", Decimal(80), True, "eligible"),
    )
    snapshot_a = RankingSnapshot.create(
        date(2026, 1, 2), revision_a.revision_id, uuid4(), uuid4(), members
    )
    snapshot_b = RankingSnapshot.create(
        date(2026, 1, 2), revision_b.revision_id, uuid4(), uuid4(), members
    )
    assert revision_a.definition_hash != revision_b.definition_hash
    assert snapshot_a.snapshot_id != snapshot_b.snapshot_id
    assert snapshot_a.members[0].instrument_id == "ABC"


def test_strategy_rejects_weights_that_do_not_sum_to_one():
    with pytest.raises(DomainValidationError, match="sum to one"):
        StrategyRevision("momentum", uuid4(), "1.0.0", uuid4(), {"trend": Decimal("0.9")}, ())


def test_strategy_api_ranks_feature_values_deterministically():
    strategy = StrategyRevision(
        "momentum", uuid4(), "1.0.0", uuid4(), {"return": Decimal(1)}, (uuid4(),)
    )
    ranking = rank_feature_values(
        date(2026, 1, 2),
        strategy,
        uuid4(),
        {"A": {"return": Decimal("0.2")}, "B": {"return": Decimal("0.1")}},
        (uuid4(),),
    )
    assert [item.instrument_id for item in ranking.members] == ["A", "B"]
    assert ranking.members[0].rank == 1


def test_retained_strategies_are_named():
    assert RETAINED_STRATEGIES == frozenset({"momentum", "positional_trend_following"})
