"""Tests for the content-addressed indicator node cache."""

from datetime import date

import pytest

from src.application.node_cache import IndicatorNodeCache
from src.application.sqlite import sqlite_connection
from src.platform_kernel import DomainValidationError


@pytest.fixture
def cache(tmp_path) -> IndicatorNodeCache:
    return IndicatorNodeCache(tmp_path / "cache.db")


class TestIndicatorNodeCache:
    def test_put_and_get_single(self, cache):
        cache.put("hash1", "RELIANCE", date(2026, 1, 1), 42.5, "snap1", market_revision="1", implementation_revision="test")
        result = cache.get("hash1", "RELIANCE", date(2026, 1, 1), market_revision="1", implementation_revision="test")
        assert result == 42.5

    def test_get_missing_returns_none(self, cache):
        result = cache.get("nonexistent", "RELIANCE", date(2026, 1, 1), market_revision="1", implementation_revision="test")
        assert result is None

    def test_put_replaces_existing(self, cache):
        cache.put("hash1", "RELIANCE", date(2026, 1, 1), 42.5, "snap1", market_revision="1", implementation_revision="test")
        cache.put("hash1", "RELIANCE", date(2026, 1, 1), 99.9, "snap2", market_revision="1", implementation_revision="test")
        result = cache.get("hash1", "RELIANCE", date(2026, 1, 1), market_revision="1", implementation_revision="test")
        assert result == 99.9

    def test_get_series(self, cache):
        for i in range(1, 6):
            cache.put("hash1", "RELIANCE", date(2026, 1, i), float(i * 10), "snap1", market_revision="1", implementation_revision="test")
        series = cache.get_series("hash1", "RELIANCE", date(2026, 1, 1), date(2026, 1, 5), market_revision="1", implementation_revision="test")
        assert len(series) == 5
        assert series["2026-01-01"] == 10.0
        assert series["2026-01-05"] == 50.0

    def test_get_series_partial_range(self, cache):
        for i in range(1, 6):
            cache.put("hash1", "RELIANCE", date(2026, 1, i), float(i), "snap1", market_revision="1", implementation_revision="test")
        series = cache.get_series("hash1", "RELIANCE", date(2026, 1, 2), date(2026, 1, 4), market_revision="1", implementation_revision="test")
        assert len(series) == 3

    def test_put_bulk(self, cache):
        values = {
            "RELIANCE": {"2026-01-01": 100.0, "2026-01-02": 101.0},
            "TCS": {"2026-01-01": 200.0, "2026-01-02": 201.0},
        }
        written = cache.put_bulk("hash1", values, "snap1", market_revisions={"REL":"1","RELIANCE":"1","TCS":"1"}, implementation_revision="test")
        assert written == 4
        assert cache.get("hash1", "RELIANCE", date(2026, 1, 1), market_revision="1", implementation_revision="test") == 100.0
        assert cache.get("hash1", "TCS", date(2026, 1, 2), market_revision="1", implementation_revision="test") == 201.0

    def test_get_bulk(self, cache):
        cache.put_bulk("hash_a", {
            "RELIANCE": {"2026-01-01": 10.0},
            "TCS": {"2026-01-01": 20.0},
        }, "snap1", market_revisions={"REL":"1","RELIANCE":"1","TCS":"1"}, implementation_revision="test")
        cache.put_bulk("hash_b", {
            "RELIANCE": {"2026-01-01": 30.0},
        }, "snap1", market_revisions={"REL":"1","RELIANCE":"1","TCS":"1"}, implementation_revision="test")

        result = cache.get_bulk({"hash_a", "hash_b"}, date(2026, 1, 1), date(2026, 1, 1), revisions={"RELIANCE":"1","TCS":"1"}, implementation_revision="test")
        assert result["hash_a"]["RELIANCE"]["2026-01-01"] == 10.0
        assert result["hash_a"]["TCS"]["2026-01-01"] == 20.0
        assert result["hash_b"]["RELIANCE"]["2026-01-01"] == 30.0

    def test_has_coverage_true(self, cache):
        for i in range(1, 4):
            cache.put("hash1", "REL", date(2026, 1, i), float(i), "snap1", market_revision="1", implementation_revision="test")
        assert cache.has_coverage("hash1", "REL", {"2026-01-01", "2026-01-02", "2026-01-03"}, market_revision="1", implementation_revision="test")

    def test_has_coverage_false(self, cache):
        cache.put("hash1", "REL", date(2026, 1, 1), 1.0, "snap1", market_revision="1", implementation_revision="test")
        assert not cache.has_coverage("hash1", "REL", {"2026-01-01", "2026-01-02"}, market_revision="1", implementation_revision="test")

    def test_has_coverage_empty_dates(self, cache):
        assert cache.has_coverage("hash1", "REL", set(), market_revision="1", implementation_revision="test")

    def test_cached_node_hashes(self, cache):
        cache.put("hash_x", "REL", date(2026, 1, 1), 1.0, "snap1", market_revision="1", implementation_revision="test")
        cache.put("hash_y", "REL", date(2026, 1, 1), 2.0, "snap1", market_revision="1", implementation_revision="test")
        hashes = cache.cached_node_hashes()
        assert hashes == {"hash_x", "hash_y"}

    def test_row_count(self, cache):
        assert cache.row_count() == 0
        cache.put("hash1", "REL", date(2026, 1, 1), 1.0, "snap1", market_revision="1", implementation_revision="test")
        cache.put("hash1", "REL", date(2026, 1, 2), 2.0, "snap1", market_revision="1", implementation_revision="test")
        cache.put("hash2", "REL", date(2026, 1, 1), 3.0, "snap1", market_revision="1", implementation_revision="test")
        assert cache.row_count() == 3
        assert cache.row_count("hash1") == 2
        assert cache.row_count("hash2") == 1

    def test_cross_strategy_sharing(self, cache):
        """Two strategies referencing the same indicator share cached values."""
        # Both strategies use the same content hash for EMA(50)
        ema_hash = "shared_ema50_hash"
        cache.put(ema_hash, "RELIANCE", date(2026, 1, 1), 123.45, "strategy1_run", market_revision="1", implementation_revision="test")
        # Strategy 2 can read the same cached value
        value = cache.get(ema_hash, "RELIANCE", date(2026, 1, 1), market_revision="1", implementation_revision="test")
        assert value == 123.45


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_nonfinite_cache_values_rejected(cache, value):
    with pytest.raises(DomainValidationError, match="finite"):
        cache.put("node", "REL", date(2026, 1, 1), value, "source",
                  market_revision="1", implementation_revision="test")


def test_old_cache_rows_and_wrong_revisions_never_return_a_hit(cache):
    with sqlite_connection(cache.database) as connection:
        connection.execute("""INSERT INTO indicator_node_cache
            (node_hash,instrument_id,as_of_date,value_json,source_snapshot_id,calculated_at,market_revision,implementation_revision)
            VALUES ('old','REL','2026-01-01','42','old-source','2026-01-01','','')""")
    day = date(2026, 1, 1)
    assert cache.get("old", "REL", day, market_revision="1", implementation_revision="test") is None
    with pytest.raises(TypeError):
        cache.get("old", "REL", day)
    cache.put("new", "REL", day, 10, "new-source", market_revision="1", implementation_revision="test")
    assert cache.get("new", "REL", day, market_revision="1", implementation_revision="test") == 10
    assert cache.get("new", "REL", day, market_revision="2", implementation_revision="test") is None
    assert cache.get("new", "REL", day, market_revision="1", implementation_revision="other") is None
    assert not cache.has_coverage("new", "REL", {day.isoformat()}, market_revision="2", implementation_revision="test")
    assert cache.get_bulk({"new"}, day, day, revisions={"REL": "2"}, implementation_revision="test")["new"] == {}
    with pytest.raises(DomainValidationError, match="revisions"):
        cache.put("new", "REL", day, 10, "bad", market_revision="", implementation_revision="test")
