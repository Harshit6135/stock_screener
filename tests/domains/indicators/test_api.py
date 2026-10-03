from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.domains.indicators.api import IndicatorConfiguration, IndicatorRevision, compute_feature


def test_indicator_api_computes_approved_feature_values_deterministically():
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
