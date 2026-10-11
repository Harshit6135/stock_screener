import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.platform_kernel.sqlite_read_cache import SqliteReadCache


def database(path):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE inputs (value INTEGER)")
        connection.execute("INSERT INTO inputs VALUES (1)")


def test_cache_reuses_copies_and_invalidates_same_row_corrections(tmp_path):
    path = tmp_path / "source.db"
    database(path)
    cache = SqliteReadCache([path])
    reads = []

    def compute():
        reads.append(True)
        with sqlite3.connect(path) as connection:
            return {"value": connection.execute("SELECT value FROM inputs").fetchone()[0]}

    try:
        first = cache.get_or_compute("account", compute)
        first["value"] = 999
        assert cache.get_or_compute("account", compute) == {"value": 1}
        assert len(reads) == 1
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE inputs SET value=2")
        assert cache.get_or_compute("account", compute) == {"value": 2}
        assert len(reads) == 2
    finally:
        cache.close()


def test_cache_checks_each_source_and_does_not_store_during_writes(tmp_path):
    paths = [tmp_path / name for name in ("ledger.db", "market.db")]
    for path in paths:
        database(path)
    cache = SqliteReadCache(paths)
    try:
        assert cache.get_or_compute("key", lambda: 1) == 1
        with sqlite3.connect(paths[1]) as connection:
            connection.execute("UPDATE inputs SET value=2")
        assert cache.get_or_compute("key", lambda: 2) == 2

        def concurrent_write():
            with sqlite3.connect(paths[0]) as connection:
                connection.execute("UPDATE inputs SET value=3")
            return "during-write"

        assert cache.get_or_compute("other", concurrent_write) == "during-write"
        assert cache.get_or_compute("other", lambda: "fresh") == "fresh"
    finally:
        cache.close()


def test_cache_is_bounded_and_does_not_cache_failures(tmp_path):
    path = tmp_path / "source.db"
    database(path)
    cache = SqliteReadCache([path], max_entries=1)
    try:
        cache.get_or_compute("first", lambda: 1)
        cache.get_or_compute("second", lambda: 2)
        assert cache.get_or_compute("first", lambda: 3) == 3
        with pytest.raises(ValueError):
            cache.get_or_compute("failure", lambda: int("invalid"))
        assert cache.get_or_compute("failure", lambda: "retry") == "retry"
    finally:
        cache.close()


def test_independent_sections_compute_concurrently(tmp_path):
    path = tmp_path / "source.db"
    database(path)
    cache = SqliteReadCache([path])
    barrier = Barrier(2)

    def compute():
        barrier.wait(timeout=2)
        return "ready"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(cache.get_or_compute, "valuation", compute)
            second = executor.submit(cache.get_or_compute, "history", compute)
            assert first.result(timeout=3) == second.result(timeout=3) == "ready"
    finally:
        cache.close()
