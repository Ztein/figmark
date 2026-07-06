"""T-060: the on-disk cache store — LRU with a size cap, TTL, and management ops.

Pure store-level tests (no HTTP): SQLite-backed, survives reopen, evicts the
least-recently-used entry when the size cap is exceeded, expires entries older
than the max age (measured on last access), and a hit re-stamps the entry so it
becomes the youngest.
"""

from __future__ import annotations

from pathlib import Path

from figmark.cache import CacheStore


def make_store(tmp_path: Path, *, max_bytes: int = 10_000, max_age_hours: float = 1.0):
    return CacheStore(tmp_path / "cache", max_bytes=max_bytes, max_age_hours=max_age_hours)


def test_put_get_roundtrip(tmp_path: Path):
    store = make_store(tmp_path)
    store.put("key-1", b'{"markdown": "hello"}', doc_digest="d1", kind="document")
    assert store.get("key-1") == b'{"markdown": "hello"}'


def test_miss_on_unknown_key(tmp_path: Path):
    store = make_store(tmp_path)
    assert store.get("nope") is None


def test_persists_across_reopen(tmp_path: Path):
    make_store(tmp_path).put("key-1", b"payload", doc_digest="d1", kind="document")
    assert make_store(tmp_path).get("key-1") == b"payload"


def test_lru_eviction_when_size_cap_exceeded(tmp_path: Path):
    store = make_store(tmp_path, max_bytes=250)
    store.put("a", b"x" * 100, doc_digest="da", kind="document")
    store.put("b", b"x" * 100, doc_digest="db", kind="document")
    # Adding c pushes total over 250 → the least-recently-used (a) is evicted.
    store.put("c", b"x" * 100, doc_digest="dc", kind="document")
    assert store.get("a") is None
    assert store.get("b") is not None
    assert store.get("c") is not None


def test_hit_restamps_entry_to_youngest(tmp_path: Path, monkeypatch):
    """Accessing an entry must protect it from eviction: touch a, then add c —
    b (now the oldest by last access) is evicted instead of a. The touch
    happens past the sparse re-stamp window (T-074: ~1 % of the TTL), which is
    when re-stamping is guaranteed."""
    import figmark.cache as cache_mod

    now = 1_000_000.0
    monkeypatch.setattr(cache_mod.time, "time", lambda: now)
    store = make_store(tmp_path, max_bytes=250)  # TTL 1 h → re-stamp window 36 s
    store.put("a", b"x" * 100, doc_digest="da", kind="document")
    monkeypatch.setattr(cache_mod.time, "time", lambda: now + 1)
    store.put("b", b"x" * 100, doc_digest="db", kind="document")
    monkeypatch.setattr(cache_mod.time, "time", lambda: now + 60)
    assert store.get("a") is not None  # 60 s old > 36 s window → re-stamps a
    monkeypatch.setattr(cache_mod.time, "time", lambda: now + 61)
    store.put("c", b"x" * 100, doc_digest="dc", kind="document")
    assert store.get("a") is not None, "recently-read entry must survive"
    assert store.get("b") is None, "the least-recently-used entry is the one evicted"


def test_hot_reread_within_window_does_not_write(tmp_path: Path, monkeypatch):
    """T-074: a hit younger than the re-stamp window returns without writing —
    the stamp is unchanged (that is what keeps hot reads off the write lock) —
    while a hit past the window re-stamps."""
    import sqlite3

    import figmark.cache as cache_mod

    now = 1_000_000.0
    monkeypatch.setattr(cache_mod.time, "time", lambda: now)
    store = make_store(tmp_path)  # TTL 1 h → window 36 s

    def stamp() -> float:
        with sqlite3.connect(store.db_path) as conn:
            return conn.execute("SELECT last_accessed FROM entries WHERE key = 'k'").fetchone()[0]

    store.put("k", b"v", doc_digest="d", kind="document")
    monkeypatch.setattr(cache_mod.time, "time", lambda: now + 5)
    assert store.get("k") is not None
    assert stamp() == now, "a hot re-read within the window must not write"
    monkeypatch.setattr(cache_mod.time, "time", lambda: now + 60)
    assert store.get("k") is not None
    assert stamp() == now + 60, "a read past the window must re-stamp"


def test_expired_entry_is_a_miss(tmp_path: Path, monkeypatch):
    import figmark.cache as cache_mod

    now = 1_000_000.0
    monkeypatch.setattr(cache_mod.time, "time", lambda: now)
    store = make_store(tmp_path, max_age_hours=2.0)
    store.put("a", b"payload", doc_digest="da", kind="document")

    monkeypatch.setattr(cache_mod.time, "time", lambda: now + 1.5 * 3600)
    assert store.get("a") is not None, "younger than max age → hit"

    monkeypatch.setattr(cache_mod.time, "time", lambda: now + 1.5 * 3600 + 2.1 * 3600)
    assert store.get("a") is None, "older than max age since last access → expired"


def test_hit_extends_lifetime(tmp_path: Path, monkeypatch):
    """Age is measured from LAST ACCESS: a hit resets the TTL clock."""
    import figmark.cache as cache_mod

    now = 1_000_000.0
    monkeypatch.setattr(cache_mod.time, "time", lambda: now)
    store = make_store(tmp_path, max_age_hours=2.0)
    store.put("a", b"payload", doc_digest="da", kind="document")

    for step in range(1, 5):  # touch every 1.5h — never 2h since last access
        monkeypatch.setattr(cache_mod.time, "time", lambda s=step: now + s * 1.5 * 3600)
        assert store.get("a") is not None


def test_oversized_payload_is_not_retained(tmp_path: Path):
    """An entry bigger than the whole cap must not wipe the cache and stay."""
    store = make_store(tmp_path, max_bytes=100)
    store.put("small", b"x" * 40, doc_digest="ds", kind="document")
    store.put("huge", b"x" * 500, doc_digest="dh", kind="document")
    assert store.get("huge") is None, "an oversized entry cannot be cached"
    assert store.get("small") is not None, "existing entries must not be wiped for it"


def test_delete_document_removes_all_its_entries(tmp_path: Path):
    store = make_store(tmp_path)
    store.put("k1", b"v1", doc_digest="dockA", kind="document")
    store.put("k2", b"v2", doc_digest="dockA", kind="document")  # other fingerprint
    store.put("k3", b"v3", doc_digest="dockB", kind="document")
    assert store.delete_document("dockA") == 2
    assert store.get("k1") is None and store.get("k2") is None
    assert store.get("k3") == b"v3"


def test_clear_empties_everything(tmp_path: Path):
    store = make_store(tmp_path)
    store.put("k1", b"v1", doc_digest="d1", kind="document")
    store.put("k2", b"v2", doc_digest="d2", kind="description")
    assert store.clear() == 2
    assert store.get("k1") is None and store.get("k2") is None
    assert store.stats()["entries"] == 0


def test_stats_reports_size_and_counts(tmp_path: Path):
    store = make_store(tmp_path, max_bytes=10_000, max_age_hours=48)
    store.put("k1", b"x" * 100, doc_digest="d1", kind="document")
    store.put("k2", b"y" * 50, doc_digest="d2", kind="description")
    s = store.stats()
    assert s["entries"] == 2
    assert s["total_bytes"] == 150
    assert s["max_bytes"] == 10_000
    assert s["max_age_hours"] == 48


def test_upsert_replaces_payload_and_size(tmp_path: Path):
    store = make_store(tmp_path)
    store.put("k", b"x" * 100, doc_digest="d", kind="document")
    store.put("k", b"y" * 10, doc_digest="d", kind="document")
    assert store.get("k") == b"y" * 10
    assert store.stats()["total_bytes"] == 10


# --- T-064: hit/miss telemetry ---------------------------------------------


def test_hit_and_miss_counters_per_kind(tmp_path: Path):
    store = make_store(tmp_path)
    store.put("doc-k", b"v", doc_digest="d1", kind="document")
    store.put("desc-k", b"t", doc_digest="d1", kind="description")
    assert store.get("doc-k") is not None  # document hit
    assert store.get("missing") is None  # document miss
    assert store.get("desc-k", kind="description") is not None  # description hit
    assert store.get("nope", kind="description") is None  # description miss
    s = store.stats()
    assert s["hits"] == {"document": 1, "description": 1}
    assert s["misses"] == {"document": 1, "description": 1}
    assert s["hit_rate"] == {"document": 0.5, "description": 0.5}


def test_hit_rate_is_null_before_any_traffic(tmp_path: Path):
    s = make_store(tmp_path).stats()
    assert s["hit_rate"] == {"document": None, "description": None}
    assert s["evictions"] == 0 and s["expirations"] == 0


def test_expiry_counts_as_expiration_and_miss(tmp_path: Path):
    store = make_store(tmp_path, max_age_hours=1.0)
    store.put("k", b"v", doc_digest="d", kind="document")
    # Backdate the entry beyond the TTL, as the existing expiry test does.
    import sqlite3

    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE entries SET last_accessed = last_accessed - 7200")
    assert store.get("k") is None
    s = store.stats()
    assert s["expirations"] == 1
    assert s["misses"]["document"] == 1
    assert s["total_bytes"] == 0


def test_eviction_counter_increments(tmp_path: Path):
    store = make_store(tmp_path, max_bytes=250)
    store.put("a", b"x" * 100, doc_digest="da", kind="document")
    store.put("b", b"x" * 100, doc_digest="db", kind="document")
    store.put("c", b"x" * 100, doc_digest="dc", kind="document")  # evicts a
    assert store.stats()["evictions"] == 1


def test_counters_survive_reopen(tmp_path: Path):
    """Hit/miss counts are buffered in memory (T-074) and flushed on writes,
    stats() and close() — a graceful shutdown persists them."""
    store = make_store(tmp_path)
    store.put("k", b"v", doc_digest="d", kind="document")
    assert store.get("k") is not None
    assert store.get("gone") is None
    store.close()
    reopened = make_store(tmp_path)
    s = reopened.stats()
    assert s["hits"]["document"] == 1 and s["misses"]["document"] == 1


# --- T-072: a broken cache degrades loudly, never fatally ------------------


def _corrupt_db(store: CacheStore) -> None:
    """Overwrite the database with garbage, as disk trouble would."""
    store.close()  # drop pooled connections — the next one sees the damage
    store.db_path.write_bytes(b"this is not a sqlite database " * 64)
    for suffix in ("-wal", "-shm"):
        store.db_path.with_name(store.db_path.name + suffix).unlink(missing_ok=True)


def test_corrupt_db_at_open_is_quarantined_and_rebuilt(tmp_path: Path, caplog):
    """A corrupt cache file must never hold the service down: it is renamed
    aside (kept for inspection), a fresh store is created, and the incident is
    logged at ERROR."""
    import logging

    first = make_store(tmp_path)
    first.put("k", b"v", doc_digest="d", kind="document")
    first.close()
    _corrupt_db(first)
    with caplog.at_level(logging.ERROR, logger="figmark.cache"):
        reopened = make_store(tmp_path)
    assert "quarantining" in caplog.text
    assert list((tmp_path / "cache").glob("cache.sqlite3.corrupt-*")), "kept for inspection"
    reopened.put("k2", b"v2", doc_digest="d", kind="document")
    assert reopened.get("k2") == b"v2", "the rebuilt store must work"


def test_get_on_corrupted_store_is_a_loud_miss_not_an_error(tmp_path: Path, caplog):
    import logging

    store = make_store(tmp_path)
    store.put("k", b"v", doc_digest="d", kind="document")
    _corrupt_db(store)
    with caplog.at_level(logging.ERROR, logger="figmark.cache"):
        assert store.get("k") is None, "a broken cache reads as a miss"
    assert "cache get failed" in caplog.text, "degraded, but loud"


def test_put_on_corrupted_store_is_dropped_not_raised(tmp_path: Path, caplog):
    """The put runs AFTER a successful (paid-for) conversion — it must never
    throw that result away."""
    import logging

    store = make_store(tmp_path)
    store.put("seed", b"v", doc_digest="d", kind="document")
    _corrupt_db(store)
    with caplog.at_level(logging.ERROR, logger="figmark.cache"):
        store.put("k", b"v", doc_digest="d", kind="document")  # must not raise
    assert "cache put failed" in caplog.text


def test_stats_exposes_error_counter(tmp_path: Path):
    store = make_store(tmp_path)
    assert store.stats()["errors"] == 0


def test_management_ops_still_raise_on_a_broken_store(tmp_path: Path):
    """Only the request path degrades: an operator deleting for compliance
    must see the failure (T-072)."""
    import sqlite3

    import pytest

    store = make_store(tmp_path)
    store.put("k", b"v", doc_digest="d", kind="document")
    _corrupt_db(store)
    with pytest.raises(sqlite3.Error):
        store.delete_document("d")


# --- T-074: behaviour under concurrent access -------------------------------


def test_concurrent_readers_and_writers_complete_without_errors(tmp_path: Path):
    import threading

    store = make_store(tmp_path, max_bytes=1_000_000)
    for i in range(20):
        store.put(f"seed-{i}", b"v" * 50, doc_digest="d", kind="description")
    errors: list[BaseException] = []

    def reader(tid: int) -> None:
        try:
            for i in range(50):
                store.get(f"seed-{(tid + i) % 20}", kind="description")
        except BaseException as e:  # noqa: BLE001 — the count IS the assertion
            errors.append(e)

    def writer(tid: int) -> None:
        try:
            for i in range(25):
                store.put(f"w-{tid}-{i}", b"x" * 50, doc_digest="d", kind="description")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=reader, args=(t,)) for t in range(6)] + [
        threading.Thread(target=writer, args=(t,)) for t in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert store.stats()["errors"] == 0, "no degraded ops under plain concurrency"
    assert store.get("seed-0", kind="description") is not None


def test_running_total_matches_reality_through_churn(tmp_path: Path):
    """The maintained total_bytes counter (which replaced the per-put SUM)
    must agree with the real sum after puts, upserts, deletes and clear."""
    store = make_store(tmp_path)
    store.put("k1", b"x" * 100, doc_digest="d1", kind="document")
    store.put("k2", b"y" * 50, doc_digest="d2", kind="document")
    store.put("k1", b"z" * 10, doc_digest="d1", kind="document")  # upsert smaller
    store.delete_document("d2")
    assert store.stats()["total_bytes"] == 10
    store.clear()
    assert store.stats()["total_bytes"] == 0


# --- T-076: the operational envelope -----------------------------------------


def test_schema_version_mismatch_is_dropped_loudly_not_quarantined(tmp_path: Path, caplog):
    """A database written by another figmark release (different schema version)
    is disposable derived data: dropped and recreated with a WARNING that says
    so — not mislabelled 'corrupt', not kept, and never a crash."""
    import logging
    import sqlite3

    d = tmp_path / "cache"
    d.mkdir()
    conn = sqlite3.connect(d / "cache.sqlite3")
    conn.execute("CREATE TABLE entries (key TEXT PRIMARY KEY, payload BLOB)")  # an "old" schema
    conn.execute("INSERT INTO entries VALUES ('stale', x'00')")
    conn.commit()
    conn.close()

    with caplog.at_level(logging.WARNING, logger="figmark.cache"):
        store = make_store(tmp_path)
    assert "schema version" in caplog.text
    assert not list(d.glob("cache.sqlite3.corrupt-*")), "an old schema is not corruption"
    assert store.get("stale") is None, "old-schema data is gone"
    store.put("k", b"v", doc_digest="d", kind="document")
    assert store.get("k") == b"v", "the recreated store must work"


def test_matching_schema_version_survives_reopen(tmp_path: Path, caplog):
    """The version gate must not touch a healthy database from this release."""
    import logging

    make_store(tmp_path).put("k", b"v", doc_digest="d", kind="document")
    with caplog.at_level(logging.WARNING, logger="figmark.cache"):
        assert make_store(tmp_path).get("k") == b"v"
    assert "schema version" not in caplog.text


def test_cache_dir_and_db_are_owner_only(tmp_path: Path):
    """The store holds converted document content in cleartext — the directory
    and the database (whose permissions SQLite copies onto -wal/-shm) must not
    be readable by group/other."""
    store = make_store(tmp_path)
    store.put("k", b"v", doc_digest="d", kind="document")
    assert (tmp_path / "cache").stat().st_mode & 0o777 == 0o700
    assert store.db_path.stat().st_mode & 0o077 == 0


def test_pre_existing_loose_directory_is_tightened_loudly(tmp_path: Path, caplog):
    import logging
    import os

    d = tmp_path / "cache"
    d.mkdir()
    os.chmod(d, 0o755)
    with caplog.at_level(logging.WARNING, logger="figmark.cache"):
        make_store(tmp_path)
    assert d.stat().st_mode & 0o777 == 0o700
    assert "tightened" in caplog.text


def test_clear_returns_disk_space(tmp_path: Path):
    """The file must not keep its high-water mark after a full wipe: an
    operator who clears a big cache should see the disk usage drop (T-076)."""
    store = make_store(tmp_path, max_bytes=5_000_000)
    for i in range(40):
        store.put(f"k-{i}", b"z" * 100_000, doc_digest="d", kind="document")
    before = store.stats()["disk_bytes"]
    assert before > 4_000_000
    store.clear()
    assert store.stats()["disk_bytes"] < 200_000, "freed pages go back to the OS"


def test_stats_reports_disk_bytes(tmp_path: Path):
    """disk_bytes is the real filesystem footprint (db + WAL) — at least the
    logical payload total, so volume sizing can be done from observation."""
    store = make_store(tmp_path, max_bytes=1_000_000)
    store.put("k", b"v" * 10_000, doc_digest="d", kind="document")
    s = store.stats()
    assert s["disk_bytes"] >= s["total_bytes"] > 0
