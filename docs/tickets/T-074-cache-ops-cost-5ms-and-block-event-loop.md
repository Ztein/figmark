# T-074: Every cache operation costs ~5 ms and runs blocking SQLite on the event loop

**Status:** Open
**Priority:** Medium — correctness is unaffected, but the cache is ~80× slower
than it needs to be, cache *reads* contend with writes, and a large `put` can
freeze the event loop (including `/healthz`) long enough to matter in an
orchestrated deployment.

## Symptom

Micro-benchmark of `CacheStore` (macOS, local SSD; medians over 300 gets /
100 puts, ~200 kB document payload, 500 small description entries present):

| Variant | `get` median | `put` median |
|---|---|---|
| Current `CacheStore` | **4.9 ms** | **5.1 ms** |
| Same, but read-only `get` | 0.59 ms | – |
| Same, but `PRAGMA synchronous=NORMAL` | 1.3 ms | 1.2 ms |
| Persistent connection + `NORMAL` | **0.06 ms** | **0.01 ms** |

Under 8 concurrent threads doing gets: median 3 ms, p95 10 ms, max 65 ms — all
reads serialise against the WAL write lock, because every read *is* a write.

Where it lands:

- The pipeline's job-gathering loop does one `shared_cache.get` per figure,
  serially, before any description job is scheduled — a 200-figure document
  pays ~1 s of cache lookups up front, plus one `put` per generated
  description from the parallel worker threads.
- `store.get`/`store.put` in `convert_endpoint` are called directly inside an
  `async def` — blocking SQLite (fsync, eviction loop) on the event loop. The
  65 ms tail above is the whole process not answering anything, `/healthz`
  included.

## Root cause

Three compounding choices in `cache.py`:

1. **A new SQLite connection per operation** (`_conn()`), never explicitly
   closed — `with conn:` only manages the transaction; prompt close relies on
   CPython refcounting. Connection setup + pragma per call.
2. **Every read is a write transaction.** `get()` re-stamps `last_accessed`
   and bumps counters, so each hit commits — and with WAL's default
   `synchronous=FULL`, each commit fsyncs. The LRU bookkeeping puts reads on
   the writer lock.
3. **No threadpool hop at the async call sites** in `api.py`.

## Impact

- Latency floor of ~10 ms per request just for cache bookkeeping; up to
  seconds of serial lookups for figure-heavy documents.
- Event-loop stalls during large `put`s/evictions → all in-flight requests and
  health probes pause; in an orchestrated deployment a slow disk can look like
  a dead service.
- Read/write lock contention grows with exactly the traffic the cache is
  supposed to absorb.

## Options

1. **Thread-local persistent connections + `synchronous=NORMAL` + sparse LRU
   re-stamp + threadpool at the async call sites.** One cached connection per
   thread (`threading.local`); `PRAGMA synchronous=NORMAL` (the standard WAL
   pairing — worst case on power loss is losing the very last commit, which
   for a cache of reproducible derived data is irrelevant); only re-stamp
   `last_accessed` when the existing stamp is older than ~1 % of the TTL, so
   hot keys read lock-free; wrap endpoint calls in `run_in_threadpool`.
   Measured effect: ~5 ms → ~0.06 ms per op, read path mostly lock-free. No
   new dependencies.
2. **Batch the pipeline's lookups** (`get_many` for all candidate keys in one
   query before job gathering). Attacks only the serial-lookup symptom; at
   60 µs per get after option 1 it buys nothing measurable. Only worth
   considering if option 1 is somehow off the table.
3. **Move the cache off SQLite** (e.g. Redis/keydb sidecar). Solves the same
   problems plus multi-process, at the cost of a new runtime dependency and
   operational surface — against the lean/air-gap constraint, and unjustified
   at this scale when option 1 reaches microseconds.

Option 1. It is small, dependency-free, and removes all three causes.

## Acceptance criteria

- [ ] A `get`/`put` on a warm store costs well under 1 ms median (benchmark
      script checked in or numbers recorded in the PR, per the bench-before-code
      rule).
- [ ] Cache reads no longer take the write lock in the common case (hot key
      re-read does not commit).
- [ ] No blocking SQLite call runs on the event loop: endpoint cache access
      goes through the threadpool (verifiable in code review; bonus: a test
      asserting the loop stays responsive during a large `put`).
- [ ] Connections are owned and closed deliberately (thread-local lifecycle),
      not left to the garbage collector.
- [ ] Existing `test_cache_store.py` semantics all still pass (LRU order, TTL,
      counters, persistence across reopen) — including with the sparse
      re-stamp, whose approximation must be covered by an adjusted lifetime
      test.
- [ ] Concurrency smoke test: parallel readers/writers complete without
      `database is locked` errors and without unbounded tail latency.
