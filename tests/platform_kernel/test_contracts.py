from uuid import uuid4

import pytest

from src.platform_kernel import CommandMetadata, DomainValidationError
from src.platform_kernel.contracts import AggregateVersion


def test_command_metadata_rejects_negative_expected_version():
    with pytest.raises(DomainValidationError, match="must not be negative"):
        CommandMetadata(idempotency_key=uuid4(), expected_version=AggregateVersion(-1))
