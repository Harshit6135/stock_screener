from decimal import Decimal
from uuid import uuid4

import pytest

from src.platform_kernel import CommandMetadata, DomainValidationError, Money, Quantity
from src.platform_kernel.contracts import AggregateVersion


def test_money_rejects_non_finite_amounts():
    with pytest.raises(DomainValidationError, match="finite"):
        Money(Decimal("NaN"))


def test_quantity_requires_positive_integer_units():
    for invalid_value in (0, -1, 1.5, True):
        with pytest.raises(DomainValidationError, match="positive integer"):
            Quantity(invalid_value)


def test_command_metadata_rejects_negative_expected_version():
    with pytest.raises(DomainValidationError, match="must not be negative"):
        CommandMetadata(idempotency_key=uuid4(), expected_version=AggregateVersion(-1))


def test_money_normalises_numeric_input_to_decimal():
    money = Money("123.45")

    assert money.amount == Decimal("123.45")
    assert money.currency == "INR"
