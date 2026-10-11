import pytest

from src.platform_kernel import FrozenDict, freeze_value


def test_frozen_dict_prevents_mutation():
    data = FrozenDict({"a": 1, "b": 2})
    assert data["a"] == 1
    with pytest.raises(TypeError, match="mapping is immutable"):
        data["a"] = 3
    with pytest.raises(TypeError, match="mapping is immutable"):
        data.pop("a")
    with pytest.raises(TypeError, match="mapping is immutable"):
        data.clear()


def test_freeze_value_recursively_freezes_structures():
    raw = {"nested": {"key": "val"}, "list": [1, 2], "set": {3, 4}}
    frozen = freeze_value(raw)
    assert isinstance(frozen, FrozenDict)
    assert isinstance(frozen["nested"], FrozenDict)
    assert isinstance(frozen["list"], tuple)
    assert isinstance(frozen["set"], frozenset)
