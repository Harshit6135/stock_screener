from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.indicators import IndicatorConfiguration, IndicatorRevision, compute_feature
from src.strategies import StrategyRevision, rank_feature_values


def test_approved_feature_and_ranking_pipeline_is_deterministic():
    revision = IndicatorRevision("simple_return", "1.0.0", ("close",), ("return",), {}, 2)
    configuration = IndicatorConfiguration.create(revision, "return")
    feature = compute_feature(
        configuration,
        revision,
        uuid4(),
        date(2026, 1, 2),
        {"A": (Decimal(10), Decimal(12)), "B": (Decimal(10), Decimal(11))},
    )
    assert {item.instrument_id: item.value for item in feature.values} == {
        "A": Decimal("0.2"),
        "B": Decimal("0.1"),
    }
    strategy = StrategyRevision(
        "momentum",
        uuid4(),
        "1.0.0",
        uuid4(),
        {"return": Decimal(1)},
        (configuration.configuration_id,),
    )
    ranking = rank_feature_values(
        date(2026, 1, 2),
        strategy,
        uuid4(),
        {item.instrument_id: {"return": item.value} for item in feature.values},
        (feature.snapshot_id,),
    )
    assert [item.instrument_id for item in ranking.members] == ["A", "B"]
    assert ranking.members[0].rank == 1
