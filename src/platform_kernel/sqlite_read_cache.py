"""Bounded read-model reuse, invalidated by writes from any SQLite connection."""

import sqlite3
import weakref
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from threading import RLock


def _close_connections(connections):
    for connection in connections:
        connection.close()


class SqliteReadCache:
    """Track data_version on persistent read-only connections to each source.

    Versions are comparable only on the same connection. All source writes
    invalidate the cache, including corrections that leave row counts unchanged.
    Readers receive copies so response decoration cannot alter cached values.
    """

    def __init__(self, paths, *, max_entries=8):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._paths = tuple(dict.fromkeys(Path(path).resolve() for path in paths))
        self._connections = []
        self._finalizer = weakref.finalize(self, _close_connections, self._connections)
        self._lock = RLock()
        self._entries = OrderedDict()
        self._versions = None
        self._max_entries = max_entries
        self._closed = False

    def _source_versions(self):
        if self._closed:
            raise RuntimeError("read cache is closed")
        if not self._connections:
            try:
                for path in self._paths:
                    connection = sqlite3.connect(
                        path.as_uri() + "?mode=ro", uri=True, check_same_thread=False
                    )
                    self._connections.append(connection)
            except Exception:
                _close_connections(self._connections)
                self._connections.clear()
                raise
        return tuple(
            connection.execute("PRAGMA data_version").fetchone()[0]
            for connection in self._connections
        )

    def get_or_compute(self, key, compute):
        with self._lock:
            versions = self._source_versions()
            if versions != self._versions:
                self._entries.clear()
                self._versions = versions
            if key in self._entries:
                self._entries.move_to_end(key)
                return deepcopy(self._entries[key])
        # Independent page sections must not wait behind another calculation.
        result = compute()
        with self._lock:
            current_versions = self._source_versions()
            if current_versions != self._versions:
                self._entries.clear()
                self._versions = current_versions
            # Do not reuse a result computed while an input database changed.
            if current_versions == versions:
                self._entries[key] = deepcopy(result)
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
            return result

    def close(self):
        with self._lock:
            self._finalizer()
            self._connections.clear()
            self._entries.clear()
            self._versions = None
            self._closed = True
