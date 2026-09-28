"""Tests for the content-addressed indicator node cache."""

import os
import shutil
import tempfile
from datetime import date
from pathlib import Path

import pytest

from src.application.node_cache import IndicatorNodeCache


@pytest.fixture
def cache() -> IndicatorNodeCache:
    test_dir = Path(__file__).resolve().parent.parent / ".test-tmp-node-cache"
    test_dir.mkdir(parents=True, exist_ok=True)
    db_path = test_dir / "test_cache.db"
    if db_path.exists():
        db_path.unlink()
    yield IndicatorNodeCache(db_path)
    # Cleanup
    try:
        shutil.rmtree(test_dir, ignore_errors=True)
    except Exception:
        pass


class TestIndicatorNodeCache:
    def test_put_and_get_single(self, cache):
        cache.put("hash1", "RELIANCE", date(2026, 1, 1), 42.5, "snap1")
        result = cache.get("hash1", "RELIANCE", date(2026, 1, 1))
        assert result == 42.5

    def test_get_missing_returns_none(self, cache):
        result = cache.get("nonexistent", "RELIANCE", date(2026, 1, 1))
        assert result is None

    def test_put_replaces_existing(self, cache):
        cache.put("hash1", "RELIANCE", date(2026, 1, 1), 42.5, "snap1")
        cache.put("hash1", "RELIANCE", date(2026, 1, 1), 99.9, "snap2")
        result = cache.get("hash1", "RELIANCE", date(2026, 1, 1))
        assert result == 99.9

    def test_get_series(self, cache):
        for i in range(1, 6):
            cache.put("hash1", "RELIANCE", date(2026, 1, i), float(i * 10), "snap1")
        series = cache.get_series("hash1", "RELIANCE", date(2026, 1, 1), date(2026, 1, 5))
        assert len(series) == 5
        assert series["2026-01-01"] == 10.0
        assert series["2026-01-05"] == 50.0

    def test_get_series_partial_range(self, cache):
        for i in range(1, 6):
            cache.put("hash1", "RELIANCE", date(2026, 1, i), float(i), "snap1")
        series = cache.get_series("hash1", "RELIANCE", date(2026, 1, 2), date(2026, 1, 4))
        assert len(series) == 3

    def test_put_bulk(self, cache):
        values = {
            "RELIANCE": {"2026-01-01": 100.0, "2026-01-02": 101.0},
            "TCS": {"2026-01-01": 200.0, "2026-01-02": 201.0},
        }
        written = cache.put_bulk("hash1", values, "snap1")
        assert written == 4
        assert cache.get("hash1", "RELIANCE", date(2026, 1, 1)) == 100.0
        assert cache.get("hash1", "TCS", date(2026, 1, 2)) == 201.0

    def test_get_bulk(self, cache):
        cache.put_bulk("hash_a", {
            "RELIANCE": {"2026-01-01": 10.0},
            "TCS": {"2026-01-01": 20.0},
        }, "snap1")
        cache.put_bulk("hash_b", {
            "RELIANCE": {"2026-01-01": 30.0},
        }, "snap1")

        result = cache.get_bulk({"hash_a", "hash_b"}, date(2026, 1, 1), date(2026, 1, 1))
        assert result["hash_a"]["RELIANCE"]["2026-01-01"] == 10.0
        assert result["hash_a"]["TCS"]["2026-01-01"] == 20.0
        assert result["hash_b"]["RELIANCE"]["2026-01-01"] == 30.0

    def test_has_coverage_true(self, cache):
        for i in range(1, 4):
            cache.put("hash1", "REL", date(2026, 1, i), float(i), "snap1")
        assert cache.has_coverage("hash1", "REL", {"2026-01-01", "2026-01-02", "2026-01-03"})

    def test_has_coverage_false(self, cache):
        cache.put("hash1", "REL", date(2026, 1, 1), 1.0, "snap1")
        assert not cache.has_coverage("hash1", "REL", {"2026-01-01", "2026-01-02"})

    def test_has_coverage_empty_dates(self, cache):
        assert cache.has_coverage("hash1", "REL", set())

    def test_cached_node_hashes(self, cache):
        cache.put("hash_x", "REL", date(2026, 1, 1), 1.0, "snap1")
        cache.put("hash_y", "REL", date(2026, 1, 1), 2.0, "snap1")
        hashes = cache.cached_node_hashes()
        assert hashes == {"hash_x", "hash_y"}

    def test_row_count(self, cache):
        assert cache.row_count() == 0
        cache.put("hash1", "REL", date(2026, 1, 1), 1.0, "snap1")
        cache.put("hash1", "REL", date(2026, 1, 2), 2.0, "snap1")
        cache.put("hash2", "REL", date(2026, 1, 1), 3.0, "snap1")
        assert cache.row_count() == 3
        assert cache.row_count("hash1") == 2
        assert cache.row_count("hash2") == 1

    def test_cross_strategy_sharing(self, cache):
        """Two strategies referencing the same indicator share cached values."""
        # Both strategies use the same content hash for EMA(50)
        ema_hash = "shared_ema50_hash"
        cache.put(ema_hash, "RELIANCE", date(2026, 1, 1), 123.45, "strategy1_run")
        # Strategy 2 can read the same cached value
        value = cache.get(ema_hash, "RELIANCE", date(2026, 1, 1))
        assert value == 123.45
