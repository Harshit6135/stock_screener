from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.indicators import IndicatorConfiguration, IndicatorRevision
from src.platform_kernel import DomainValidationError
from src.strategies import PortfolioPolicyRevision, RankingMember, RankingSnapshot, StrategyRevision


def test_strategy_revisions_and_snapshots_are_versioned_by_input_ids():
    indicator = IndicatorRevision("ema", "1.0.0", ("close",), ("ema_50",), {"length": 50}, 50)
    configuration = IndicatorConfiguration.create(indicator, "ema_50")
    policy = PortfolioPolicyRevision("momentum-policy", uuid4(), 10, Decimal("0.25"), Decimal(2))
    revision_a = StrategyRevision(
        "momentum",
        uuid4(),
        "1.0.0",
        policy.revision_id,
        {"trend": Decimal(1)},
        (configuration.configuration_id,),
    )
    revision_b = StrategyRevision(
        "momentum",
        uuid4(),
        "1.1.0",
        policy.revision_id,
        {"trend": Decimal("0.5"), "momentum": Decimal("0.5")},
        (configuration.configuration_id,),
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
