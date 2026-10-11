from datetime import date
from uuid import uuid4

import pytest

from src.domains.reference_data import InstrumentAlias, resolve_alias
from src.platform_kernel import DomainValidationError


def test_alias_resolution_is_point_in_time():
    instrument = uuid4()
    old = InstrumentAlias(instrument, "ABC", "NSE", date(2020, 1, 1), date(2022, 12, 31), "1")
    new = InstrumentAlias(instrument, "XYZ", "NSE", date(2023, 1, 1), None, "2")

    assert resolve_alias((old, new), "ABC", "NSE", date(2021, 1, 1)) == old
    with pytest.raises(DomainValidationError, match="exactly one"):
        resolve_alias((old, new), "ABC", "NSE", date(2024, 1, 1))
