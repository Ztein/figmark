"""Cross-request cache store for the HTTP surface (T-060/T-061).

A single SQLite file holds every entry (document results and, with T-061,
shared figure descriptions) plus the bookkeeping the policies need:

- **Size cap with LRU eviction:** when the configured maximum is exceeded, the
  least-recently-used entries are deleted until the cache fits. An entry larger
  than the whole cap is never retained (it must not wipe the cache).
- **Max age (TTL):** entries older than the configured number of hours — since
  their *last access* — are expired.
- **Hit = youngest:** a ``get`` re-stamps ``last_accessed``, so a
  frequently-used entry keeps surviving both policies. The re-stamp is sparse
  (T-074): a stamp younger than ~1 % of the TTL is left alone, so a hot key is
  read without taking the write lock. Within that window the LRU order among
  entries accessed close together is approximate — irrelevant at real TTLs.
- **Management:** delete all entries for one document digest, or clear all.

SQLite gives atomic bookkeeping under concurrent requests and survives restarts
when the directory is on a persistent volume. WAL mode with
``synchronous=NORMAL`` — the WAL-recommended pairing; a power cut can cost at
most the last commit, which for a cache of reproducible derived data is
irrelevant (T-074). Connections are pooled and owned by the store: call
``close()`` (the API server does, on shutdown) to flush telemetry and release
them deliberately. Keys are caller-built (document digest + config fingerprint
+ version) so a config or version change is a clean miss — T-034 semantics.

**The request path degrades loudly, never fatally (T-072).** ``get``/``put``
are accelerators: any SQLite fault there is logged at ERROR and counted
(``stats()["errors"]``), and the call reports a miss / drops the write — a
broken cache must never fail a conversion that already succeeded. The
*management* surface (``delete_document``, ``clear``, ``stats``) still raises:
an operator deleting a document for compliance must see a failure, not a
silent no-op. A corrupt database at startup is quarantined
(``cache.sqlite3.corrupt-<ts>``, kept for inspection) and rebuilt, so a cache
file can never hold the service down.

**Operational envelope (T-076).** The schema carries a version
(``PRAGMA user_version``); a database written by a different figmark release is
dropped and recreated loudly — the cache is disposable derived data, so there
is no migration machinery. The directory and database are owner-only
(``0700``/``0600``): they hold every converted document's content in cleartext.
Freed pages are returned to the filesystem (``auto_vacuum=INCREMENTAL``, an
incremental vacuum after eviction and a vacuum+WAL-truncate after
``clear``/``delete_document``), and ``stats()`` reports the actual on-disk
footprint (``disk_bytes``) next to the logical one. The store assumes one
writer host on a local filesystem — WAL corrupts over NFS/SMB.
"""

from __future__ import annotations

import logging
import os
import queue
import sqlite3
import threading
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("figmark.cache")

# Bump on ANY change to _SCHEMA. A mismatching database (older or newer) is
# dropped and recreated at open — loudly, but with no migration machinery: the
# cache holds only reproducible derived data (T-076). Version 1 is the first
# stamped release; a pre-T-076 database reads as 0 and is dropped once.
_SCHEMA_VERSION = 1

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
# SUM(size) and is reconciled against the real sum at startup. Hit/miss counts
# are buffered in memory and flushed on any write, on stats() and on close()
# (T-074), so a pure read is not a write transaction; an unclean shutdown can
# drop a few buffered counts — telemetry, not accounting.
_COUNTER_NAMES = (
    "hits_document",
    "misses_document",
    "hits_description",
    "misses_description",
    "evictions",
    "expirations",
    "errors",
)

# Connections retained for reuse; excess concurrent ops open a transient
# connection and close it after use, so this bounds idle handles, not
# concurrency.
_POOL_SIZE = 8


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
    """SQLite-backed LRU+TTL cache. Thread-safe via a small connection pool."""

    def __init__(self, directory: Path, *, max_bytes: int, max_age_hours: float) -> None:
        self.directory = Path(directory)
        # Owner-only: the cache holds converted document content in cleartext
        # (T-076). mkdir's mode only applies to a directory we create; an
        # operator-provided directory with looser bits is tightened, loudly.
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._tighten_permissions(self.directory, 0o700)
        self.db_path = self.directory / "cache.sqlite3"
        self.max_bytes = int(max_bytes)
        self.max_age_seconds = float(max_age_hours) * 3600.0
        self.max_age_hours = float(max_age_hours)
        # Sparse re-stamp window (T-074): a hit younger than this since its
        # last stamp does not write. 1 % of the TTL keeps the LRU/TTL error
        # negligible while letting hot keys read lock-free.
        self._restamp_seconds = max(1.0, self.max_age_seconds * 0.01)
        self._pool: queue.LifoQueue[sqlite3.Connection] = queue.LifoQueue(maxsize=_POOL_SIZE)
        self._pending: Counter[str] = Counter()
        self._pending_lock = threading.Lock()
        self._create_db_file()
        self._init_db()

    # ------------------------------------------------------------ connections
    def _new_conn(self) -> sqlite3.Connection:
        # check_same_thread=False: connections are pooled and may be reused by
        # another thread, but never concurrently (the pool hands each out to
        # one holder at a time).
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        # Must run before anything initialises the file (journal_mode=WAL
        # writes the header): freed pages then go to the freelist where
        # incremental_vacuum can return them to the OS (T-076). On an
        # already-initialised database this is a harmless no-op.
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _connection(self):
        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            conn = self._new_conn()
        try:
            yield conn
        except BaseException:
            # The connection may be mid-transaction or attached to a broken
            # database — never return it to the pool.
            try:
                conn.close()
            except Exception:  # noqa: BLE001, S110 — already failing; close is best-effort, original error re-raised
                pass
            raise
        else:
            try:
                self._pool.put_nowait(conn)
            except queue.Full:
                conn.close()

    def _create_db_file(self) -> None:
        """Create the database file ourselves so it is born ``0600``.

        Left to SQLite it would be created with the umask (typically ``0644``)
        and hold cleartext document content group/other-readable until the
        tighten pass. The -wal/-shm sidecars inherit the database file's
        permissions (T-076). An empty file is a valid new SQLite database.
        """
        self.db_path.touch(mode=0o600, exist_ok=True)

    def _init_db(self) -> None:
        try:
            self._setup_schema()
        except sqlite3.DatabaseError:
            # T-072: a corrupt cache file must never hold the service down.
            # Quarantine it (kept for inspection) and start fresh — loudly.
            quarantine = self.db_path.with_name(f"{self.db_path.name}.corrupt-{int(time.time())}")
            logger.error(
                "cache database %s is corrupt — quarantining to %s and starting fresh",
                self.db_path,
                quarantine,
                exc_info=True,
            )
            os.replace(self.db_path, quarantine)
            for suffix in ("-wal", "-shm"):
                side = self.db_path.with_name(self.db_path.name + suffix)
                side.unlink(missing_ok=True)
            self._create_db_file()
            self._setup_schema()  # a second failure is not corruption — raise it

    def _setup_schema(self) -> None:
        conn = self._new_conn()
        try:
            # Schema version gate (T-076): a database written by a different
            # figmark release is not "corrupt" — it is simply disposable. Drop
            # and recreate loudly; no migration machinery for derived data.
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != _SCHEMA_VERSION:
                tables = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                ).fetchone()[0]
                if tables:
                    conn.close()
                    logger.warning(
                        "cache database %s has schema version %d, this release uses %d"
                        " — dropping and recreating (a cache holds only reproducible"
                        " derived data)",
                        self.db_path,
                        version,
                        _SCHEMA_VERSION,
                    )
                    self.db_path.unlink()
                    for suffix in ("-wal", "-shm"):
                        self.db_path.with_name(self.db_path.name + suffix).unlink(missing_ok=True)
                    self._create_db_file()
                    conn = self._new_conn()
            with conn:
                conn.executescript(_SCHEMA)
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                # Reconcile the running size total with reality (repairs any
                # drift from a crash mid-transaction or a pre-T-064 database).
                real_total = conn.execute("SELECT COALESCE(SUM(size), 0) FROM entries").fetchone()[
                    0
                ]
                conn.execute(
                    "INSERT INTO counters (name, value) VALUES ('total_bytes', ?)"
                    " ON CONFLICT(name) DO UPDATE SET value = ?",
                    (real_total, real_total),
                )
        finally:
            conn.close()
        # Owner-only, same rationale as the directory. SQLite gives the -wal
        # and -shm sidecars the database file's permissions, so tightening the
        # database here covers all three.
        self._tighten_permissions(self.db_path, 0o600)

    @staticmethod
    def _tighten_permissions(path: Path, mode: int) -> None:
        """Ensure ``path`` has no group/other bits; loud but never fatal.

        Best-effort because the operator may mount a volume we do not own —
        the cache must still work there, but the exposure is logged (T-076).
        """
        try:
            current = path.stat().st_mode & 0o777
            if current & 0o077:
                os.chmod(path, mode)
                logger.warning(
                    "cache path %s had permissions %o — tightened to %o"
                    " (it holds converted document content in cleartext)",
                    path,
                    current,
                    mode,
                )
        except OSError:
            logger.warning(
                "cache path %s is not owner-only and could not be tightened"
                " — it holds converted document content in cleartext",
                path,
                exc_info=True,
            )

    # --------------------------------------------------------------- counters
    def _note(self, name: str, delta: int = 1) -> None:
        with self._pending_lock:
            self._pending[name] += delta

    def _flush_pending(self, conn: sqlite3.Connection) -> None:
        """Write buffered counters. Call inside a write transaction."""
        with self._pending_lock:
            if not self._pending:
                return
            items = dict(self._pending)
            self._pending.clear()
        for name, delta in items.items():
            _bump(conn, name, delta)

    # ------------------------------------------------------------ request path
    def get(self, key: str, *, kind: str = "document") -> bytes | None:
        """Return the payload; None on miss/expiry — and on cache failure.

        ``kind`` attributes the hit/miss to the right counter (T-064):
        ``document`` for whole-conversion payloads, ``description`` for shared
        figure descriptions (SharedDescriptionCache passes it).
        """
        now = time.time()
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT payload, last_accessed, size FROM entries WHERE key = ?", (key,)
                ).fetchone()
                if row is None:
                    self._note(f"misses_{kind}")
                    return None
                payload, last_accessed, size = row
                if now - last_accessed > self.max_age_seconds:
                    with conn:
                        conn.execute("DELETE FROM entries WHERE key = ?", (key,))
                        _bump(conn, "expirations")
                        _bump(conn, "total_bytes", -size)
                        self._note(f"misses_{kind}")
                        self._flush_pending(conn)
                    return None
                self._note(f"hits_{kind}")
                if now - last_accessed > self._restamp_seconds:
                    with conn:
                        conn.execute(
                            "UPDATE entries SET last_accessed = ? WHERE key = ?", (now, key)
                        )
                        self._flush_pending(conn)
                return payload
        except sqlite3.Error:
            self._degraded("get", key)
            return None

    def put(self, key: str, payload: bytes, *, doc_digest: str, kind: str) -> None:
        """Insert/replace an entry, then enforce TTL and the size cap (LRU).

        A cache failure drops the write loudly — it never raises into the
        caller, who has a finished (paid-for) result to return (T-072).
        """
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
        try:
            with self._connection() as conn:
                with conn:
                    old = conn.execute("SELECT size FROM entries WHERE key = ?", (key,)).fetchone()
                    conn.execute(
                        "INSERT INTO entries (key, doc_digest, kind, payload, size, created,"
                        " last_accessed) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE"
                        " SET payload = excluded.payload, size = excluded.size,"
                        " last_accessed = excluded.last_accessed",
                        (key, doc_digest, kind, payload, len(payload), now, now),
                    )
                    _bump(conn, "total_bytes", len(payload) - (old[0] if old else 0))
                    self._flush_pending(conn)
                    evicted = self._evict(conn, now)
                if evicted:
                    # Return the freed pages to the filesystem so the file
                    # tracks the cap instead of holding its high-water mark
                    # forever (T-076); the truncation lands at the next WAL
                    # checkpoint. After the commit, via executescript — see
                    # _shrink for why.
                    conn.executescript("PRAGMA incremental_vacuum;")
        except sqlite3.Error:
            self._degraded("put", key)

    def _degraded(self, op: str, key: str) -> None:
        """A request-path cache failure: loud, counted, never fatal (T-072)."""
        self._note("errors")
        logger.error(
            "cache %s failed for key %s… — request continues without cache",
            op,
            key[:32],
            exc_info=True,
        )

    def _evict(self, conn: sqlite3.Connection, now: float) -> bool:
        """Enforce TTL and the size cap. Returns whether anything was removed."""
        removed = False
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
            removed = True
        while _counter(conn, "total_bytes") > self.max_bytes:
            oldest = conn.execute(
                "SELECT key, size FROM entries ORDER BY last_accessed ASC LIMIT 1"
            ).fetchone()
            if oldest is None:
                break
            conn.execute("DELETE FROM entries WHERE key = ?", (oldest[0],))
            _bump(conn, "evictions")
            _bump(conn, "total_bytes", -oldest[1])
            removed = True
        return removed

    def _shrink(self, conn: sqlite3.Connection) -> None:
        """Give deleted pages back to the OS now (after a management delete).

        Runs outside any transaction: the checkpoint must see the commit, and
        ``wal_checkpoint(TRUNCATE)`` also empties the WAL itself. Via
        ``executescript`` deliberately: it steps each statement to completion
        on every Python version, whereas ``execute(...).fetchall()`` on an
        ``incremental_vacuum`` (which frees one page per step and declares no
        result columns) steps only once on Python ≤ 3.11 — freeing one page
        instead of all of them.
        """
        conn.executescript("PRAGMA incremental_vacuum; PRAGMA wal_checkpoint(TRUNCATE);")

    # ------------------------------------------------------ management surface
    def delete_document(self, doc_digest: str) -> int:
        """Remove every entry belonging to a document digest. Returns the count.

        Management ops raise on failure — an operator must see it, not get a
        silent no-op (T-072 keeps only get/put non-fatal).
        """
        with self._connection() as conn:
            with conn:
                removed = conn.execute(
                    "SELECT COALESCE(SUM(size), 0) FROM entries WHERE doc_digest = ?",
                    (doc_digest,),
                ).fetchone()[0]
                cur = conn.execute("DELETE FROM entries WHERE doc_digest = ?", (doc_digest,))
                _bump(conn, "total_bytes", -removed)
                self._flush_pending(conn)
            self._shrink(conn)
            return cur.rowcount

    def clear(self) -> int:
        """Empty the cache entirely. Returns the number of entries removed."""
        with self._connection() as conn:
            with conn:
                cur = conn.execute("DELETE FROM entries")
                conn.execute(
                    "INSERT INTO counters (name, value) VALUES ('total_bytes', 0)"
                    " ON CONFLICT(name) DO UPDATE SET value = 0"
                )
                self._flush_pending(conn)
            self._shrink(conn)
            return cur.rowcount

    def stats(self) -> dict:
        """Storage + performance view (T-064). Counters are monotonic since the
        cache directory was created; hit rates are derived, null before any
        traffic (never a fake 0). ``errors`` counts degraded-loudly request-path
        failures (T-072)."""
        with self._connection() as conn:
            with conn:
                self._flush_pending(conn)
            entries, total = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM entries"
            ).fetchone()
            counters = {name: _counter(conn, name) for name in _COUNTER_NAMES}

        def rate(hits: int, misses: int) -> float | None:
            return round(hits / (hits + misses), 4) if hits + misses else None

        # The actual filesystem footprint (database + WAL + shm), so an
        # operator can size the volume from observation, not guesswork (T-076).
        disk_bytes = 0
        for suffix in ("", "-wal", "-shm"):
            side = self.db_path.with_name(self.db_path.name + suffix)
            try:
                disk_bytes += side.stat().st_size
            except OSError:
                pass  # sidecar absent (no WAL activity yet) — nothing to count

        return {
            "entries": entries,
            "total_bytes": total,
            "disk_bytes": disk_bytes,
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
            "errors": counters["errors"],
        }

    def close(self) -> None:
        """Flush buffered telemetry and close pooled connections deliberately.

        The API server calls this on shutdown. Best-effort: a broken database
        must not turn shutdown into a crash."""
        try:
            with self._connection() as conn, conn:
                self._flush_pending(conn)
        except sqlite3.Error:
            logger.error("cache counter flush on close failed", exc_info=True)
        while True:
            try:
                self._pool.get_nowait().close()
            except queue.Empty:
                return


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
