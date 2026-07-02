"""Cross-request cache store for the HTTP surface (T-060/T-061).

A single SQLite file holds every entry (document results and, with T-061,
shared figure descriptions) plus the bookkeeping the policies need:

- **Size cap with LRU eviction:** when the configured maximum is exceeded, the
  least-recently-used entries are deleted until the cache fits. An entry larger
  than the whole cap is never retained (it must not wipe the cache).
- **Max age (TTL):** entries older than the configured number of hours — since
  their *last access* — are expired.
- **Hit = youngest:** every ``get`` re-stamps ``last_accessed`` to now, so a
  frequently-used entry keeps surviving both policies.
- **Management:** delete all entries for one document digest, or clear all.

SQLite gives atomic bookkeeping under concurrent requests (WAL mode, one
transaction per operation) and survives restarts when the directory is on a
persistent volume. Keys are caller-built (document digest + config fingerprint
+ version) so a config or version change is a clean miss — T-034 semantics.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger("figmark.cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    key TEXT PRIMARY KEY,
    doc_digest TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload BLOB NOT NULL,
    size INTEGER NOT NULL,
    created REAL NOT NULL,
    last_accessed REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_last_accessed ON entries (last_accessed);
CREATE INDEX IF NOT EXISTS idx_doc_digest ON entries (doc_digest);
"""


class CacheStore:
    """SQLite-backed LRU+TTL cache. Thread-safe via one connection per op."""

    def __init__(self, directory: Path, *, max_bytes: int, max_age_hours: float) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / "cache.sqlite3"
        self.max_bytes = int(max_bytes)
        self.max_age_seconds = float(max_age_hours) * 3600.0
        self.max_age_hours = float(max_age_hours)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, key: str) -> bytes | None:
        """Return the payload, re-stamping last_accessed; None on miss/expiry."""
        now = time.time()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload, last_accessed FROM entries WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            payload, last_accessed = row
            if now - last_accessed > self.max_age_seconds:
                conn.execute("DELETE FROM entries WHERE key = ?", (key,))
                return None
            conn.execute("UPDATE entries SET last_accessed = ? WHERE key = ?", (now, key))
            return payload

    def put(self, key: str, payload: bytes, *, doc_digest: str, kind: str) -> None:
        """Insert/replace an entry, then enforce TTL and the size cap (LRU)."""
        if len(payload) > self.max_bytes:
            # Never admitted: evicting everything older to make room for an
            # entry that still wouldn't fit would wipe the cache for nothing.
            logger.warning(
                "cache entry larger than the whole cache cap (%d > %d bytes) — not retained",
                len(payload),
                self.max_bytes,
            )
            return
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO entries (key, doc_digest, kind, payload, size, created,"
                " last_accessed) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET"
                " payload = excluded.payload, size = excluded.size,"
                " last_accessed = excluded.last_accessed",
                (key, doc_digest, kind, payload, len(payload), now, now),
            )
            self._evict(conn, now)

    def _evict(self, conn: sqlite3.Connection, now: float) -> None:
        conn.execute("DELETE FROM entries WHERE ? - last_accessed > ?", (now, self.max_age_seconds))
        while True:
            total = conn.execute("SELECT COALESCE(SUM(size), 0) FROM entries").fetchone()[0]
            if total <= self.max_bytes:
                return
            oldest = conn.execute(
                "SELECT key FROM entries ORDER BY last_accessed ASC LIMIT 1"
            ).fetchone()
            if oldest is None:
                return
            conn.execute("DELETE FROM entries WHERE key = ?", (oldest[0],))

    def delete_document(self, doc_digest: str) -> int:
        """Remove every entry belonging to a document digest. Returns the count."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM entries WHERE doc_digest = ?", (doc_digest,))
            return cur.rowcount

    def clear(self) -> int:
        """Empty the cache entirely. Returns the number of entries removed."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM entries")
            return cur.rowcount

    def stats(self) -> dict:
        with self._conn() as conn:
            entries, total = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM entries"
            ).fetchone()
        return {
            "entries": entries,
            "total_bytes": total,
            "max_bytes": self.max_bytes,
            "max_age_hours": self.max_age_hours,
        }
