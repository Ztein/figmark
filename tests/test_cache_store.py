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


def test_hit_restamps_entry_to_youngest(tmp_path: Path):
    """Accessing an entry must protect it from eviction: touch a, then add c —
    b (now the oldest by last access) is evicted instead of a."""
    store = make_store(tmp_path, max_bytes=250)
    store.put("a", b"x" * 100, doc_digest="da", kind="document")
    store.put("b", b"x" * 100, doc_digest="db", kind="document")
    assert store.get("a") is not None  # re-stamps a to "now"
    store.put("c", b"x" * 100, doc_digest="dc", kind="document")
    assert store.get("a") is not None, "recently-read entry must survive"
    assert store.get("b") is None, "the least-recently-used entry is the one evicted"


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
    store = make_store(tmp_path)
    store.put("k", b"v", doc_digest="d", kind="document")
    assert store.get("k") is not None
    assert store.get("gone") is None
    reopened = make_store(tmp_path)
    s = reopened.stats()
    assert s["hits"]["document"] == 1 and s["misses"]["document"] == 1


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
