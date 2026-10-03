"""Composition wiring contracts for retired application services."""

from pathlib import Path

from src.gates import composition


def test_early_momentum_is_not_imported_in_composition():
    source = Path(composition.__file__).read_text()
    assert "EarlyMomentumJobs" not in source
    assert "early_momentum" not in source
