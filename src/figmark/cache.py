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
CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""

# Monotonic performance counters (T-064). Persisted in SQLite so "what has the
# cache saved us" survives restarts on a persistent volume. `total_bytes` is a
# maintained running total of entry sizes — it replaces the per-put O(n)
# SUM(size) and is reconciled against the real sum at startup.
_COUNTER_NAMES = (
    "hits_document",
    "misses_document",
    "hits_description",
    "misses_description",
    "evictions",
    "expirations",
)


def _bump(conn: sqlite3.Connection, name: str, delta: int = 1) -> None:
    conn.execute(
        "INSERT INTO counters (name, value) VALUES (?, ?)"
        " ON CONFLICT(name) DO UPDATE SET value = value + ?",
        (name, delta, delta),
    )


def _counter(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()
    return int(row[0]) if row else 0


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
            # Reconcile the running size total with reality (repairs any drift
            # from a crash mid-transaction or a pre-T-064 database).
            real_total = conn.execute("SELECT COALESCE(SUM(size), 0) FROM entries").fetchone()[0]
            conn.execute(
                "INSERT INTO counters (name, value) VALUES ('total_bytes', ?)"
                " ON CONFLICT(name) DO UPDATE SET value = ?",
                (real_total, real_total),
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, key: str, *, kind: str = "document") -> bytes | None:
        """Return the payload, re-stamping last_accessed; None on miss/expiry.

        ``kind`` attributes the hit/miss to the right counter (T-064):
        ``document`` for whole-conversion payloads, ``description`` for shared
        figure descriptions (SharedDescriptionCache passes it).
        """
        now = time.time()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload, last_accessed, size FROM entries WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                _bump(conn, f"misses_{kind}")
                return None
            payload, last_accessed, size = row
            if now - last_accessed > self.max_age_seconds:
                conn.execute("DELETE FROM entries WHERE key = ?", (key,))
                _bump(conn, "expirations")
                _bump(conn, f"misses_{kind}")
                _bump(conn, "total_bytes", -size)
                return None
            conn.execute("UPDATE entries SET last_accessed = ? WHERE key = ?", (now, key))
            _bump(conn, f"hits_{kind}")
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
            old = conn.execute("SELECT size FROM entries WHERE key = ?", (key,)).fetchone()
            conn.execute(
                "INSERT INTO entries (key, doc_digest, kind, payload, size, created,"
                " last_accessed) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET"
                " payload = excluded.payload, size = excluded.size,"
                " last_accessed = excluded.last_accessed",
                (key, doc_digest, kind, payload, len(payload), now, now),
            )
            _bump(conn, "total_bytes", len(payload) - (old[0] if old else 0))
            self._evict(conn, now)

    def _evict(self, conn: sqlite3.Connection, now: float) -> None:
        expired = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM entries WHERE ? - last_accessed > ?",
            (now, self.max_age_seconds),
        ).fetchone()
        if expired[0]:
            conn.execute(
                "DELETE FROM entries WHERE ? - last_accessed > ?", (now, self.max_age_seconds)
            )
            _bump(conn, "expirations", expired[0])
            _bump(conn, "total_bytes", -expired[1])
        while True:
            if _counter(conn, "total_bytes") <= self.max_bytes:
                return
            oldest = conn.execute(
                "SELECT key, size FROM entries ORDER BY last_accessed ASC LIMIT 1"
            ).fetchone()
            if oldest is None:
                return
            conn.execute("DELETE FROM entries WHERE key = ?", (oldest[0],))
            _bump(conn, "evictions")
            _bump(conn, "total_bytes", -oldest[1])

    def delete_document(self, doc_digest: str) -> int:
        """Remove every entry belonging to a document digest. Returns the count."""
        with self._conn() as conn:
            removed = conn.execute(
                "SELECT COALESCE(SUM(size), 0) FROM entries WHERE doc_digest = ?", (doc_digest,)
            ).fetchone()[0]
            cur = conn.execute("DELETE FROM entries WHERE doc_digest = ?", (doc_digest,))
            _bump(conn, "total_bytes", -removed)
            return cur.rowcount

    def clear(self) -> int:
        """Empty the cache entirely. Returns the number of entries removed."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM entries")
            conn.execute(
                "INSERT INTO counters (name, value) VALUES ('total_bytes', 0)"
                " ON CONFLICT(name) DO UPDATE SET value = 0"
            )
            return cur.rowcount

    def stats(self) -> dict:
        """Storage + performance view (T-064). Counters are monotonic since the
        cache directory was created; hit rates are derived, null before any
        traffic (never a fake 0)."""
        with self._conn() as conn:
            entries, total = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM entries"
            ).fetchone()
            counters = {name: _counter(conn, name) for name in _COUNTER_NAMES}

        def rate(hits: int, misses: int) -> float | None:
            return round(hits / (hits + misses), 4) if hits + misses else None

        return {
            "entries": entries,
            "total_bytes": total,
            "max_bytes": self.max_bytes,
            "max_age_hours": self.max_age_hours,
            "hits": {
                "document": counters["hits_document"],
                "description": counters["hits_description"],
            },
            "misses": {
                "document": counters["misses_document"],
                "description": counters["misses_description"],
            },
            "hit_rate": {
                "document": rate(counters["hits_document"], counters["misses_document"]),
                "description": rate(counters["hits_description"], counters["misses_description"]),
            },
            "evictions": counters["evictions"],
            "expirations": counters["expirations"],
        }


class SharedDescriptionCache:
    """The pipeline's view of the store for figure descriptions (T-061).

    Keys are content-based (image/rendered-region digest + config fingerprint),
    so the same pixels reuse one description across requests AND documents.
    Entries are attributed to the document that first created them
    (``doc_digest``): purging that document also purges the descriptions it
    introduced — later documents that relied on them simply regenerate.
    """

    def __init__(
        self, store: CacheStore, doc_digest: str, *, share_across_documents: bool = True
    ) -> None:
        self._store = store
        self._doc_digest = doc_digest
        self._share = share_across_documents

    def _key(self, key: str) -> str:
        # T-063: with sharing off, the document digest joins the key — the same
        # image in another document is a clean miss (no context bleed), while a
        # re-upload of the SAME document (same digest) still reuses.
        return key if self._share else f"{key}-doc-{self._doc_digest}"

    def get(self, key: str) -> str | None:
        payload = self._store.get(self._key(key), kind="description")
        return payload.decode("utf-8") if payload is not None else None

    def put(self, key: str, text: str) -> None:
        if text.strip():
            self._store.put(
                self._key(key),
                text.encode("utf-8"),
                doc_digest=self._doc_digest,
                kind="description",
            )
