# T-064: The cache's savings are invisible in operation — no hit/miss telemetry

**Status:** Closed — **Option 1 (+ the size-total note) shipped 2026-07-03.**
Monotonic counters (document/description hits+misses, evictions, expirations)
live in a SQLite `counters` table, bumped in `get`/`_evict`, and are reported
by `GET /v1/cache/stats` with derived per-kind hit rates (null before any
traffic — never a fake 0). Counters persist across restarts with the cache
directory. `put()`'s per-insert `SUM(size)` was replaced by a maintained
`total_bytes` running total, reconciled against the real sum at startup.
**Priority:** Low — the cache works and hits are labelled per response; what is
missing is the aggregate view an operator needs to *see* what it saves.

## Symptom

`GET /v1/cache/stats` reports what the cache *holds* (entries, bytes, caps) but
nothing about how it *performs*: no hit/miss counters, no count of model calls
or tokens avoided. An operator who wants to know "what is the cache actually
saving us?" has to grep request logs and add things up by hand. The one-off
benchmark exists (T-060: 117 s / €0.026 → 0.04 s / €0 on a hit; a revised
re-upload cut 48 calls to 2), but nothing tracks it in live operation.

## Root cause

T-060/T-061 scoped stats to storage bookkeeping; performance counters were
never part of the store.

## Impact

- The cache's value (and the right `max_size_mb`/`max_age_hours` tuning) is
  guesswork without hit-rate data — e.g. a TTL set too low would silently erase
  most of the benefit and nobody would see it.
- Follow-up decisions (T-062 partitioning, T-063 toggle) also want usage data.

## Options

1. **Counters in the store, exposed via stats.** Add monotonic counters
   (document hits/misses, description hits/misses, evictions, expirations) to
   the SQLite store — one small counters table, incremented in `get`/`_evict` —
   and report them in `GET /v1/cache/stats` together with a derived hit rate.
   Persistent across restarts, no new dependency. Recommended.
2. **In-memory counters only.** Simpler, but reset on every restart, which
   undercuts the "what has it saved us" question — with tmpfs deployments the
   process lifetime *is* the cache lifetime, so this is nearly equivalent there,
   but strictly worse on persistent volumes.
3. **Estimated-savings figures** (avoided calls × average measured cost/time)
   on top of Option 1. Nice-to-have; keep honest by labelling them estimates.

## Notes

- While touching the store: `put()` recomputes `SUM(size)` per insert — fine at
  realistic entry counts, but a maintained running total in the same counters
  table would remove the O(n) query for free if Option 1 lands.

## Acceptance criteria

- [x] `GET /v1/cache/stats` reports hits/misses (document + description
      separately), evictions and expirations, and a derived hit rate.
- [x] Counters survive a restart when the cache directory is persistent.
- [x] Tests cover counter increments for hit, miss, expiry, and eviction
      (`tests/test_cache_store.py`).
