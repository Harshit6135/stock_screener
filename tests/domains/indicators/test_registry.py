import pandas as pd
import pytest

from src.domains.indicators.registry import PandasTaAdapter
from src.platform_kernel import DomainValidationError


def test_public_indicator_parameter_validation():
    adapter = PandasTaAdapter()
    spec = adapter.spec("ema")
    assert adapter.validate_parameters(spec, {"length": 21})["length"] == 21
    with pytest.raises(DomainValidationError, match="must be numeric"):
        adapter.validate_parameters(spec, {"length": True})


def test_pandas_ta_catalogue_and_ema_are_safe_and_deterministic():
    adapter = PandasTaAdapter()
    assert {item["indicator_key"] for item in adapter.catalogue()} >= {"ema", "rsi", "atr", "macd"}
    close = pd.Series([float(value) for value in range(1, 40)])
    first = adapter.calculate("ema", {"close": close}, {"length": 10})
    second = adapter.calculate("ema", {"close": close}, {"length": 10})
    assert first.equals(second)
    assert first.index.equals(close.index)
    assert first.iloc[:9].isna().all().all()
