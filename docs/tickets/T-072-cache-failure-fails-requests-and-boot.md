# T-072: A cache failure fails the customer's request — and a corrupt cache file prevents the service from starting

**Status:** Open
**Priority:** High — the cache is an accelerator for derived, reproducible data,
yet today it sits on the critical path twice: an I/O error turns a *successful*
conversion into a 500, and a corrupt `cache.sqlite3` keeps the whole service
down. Both are availability bugs a professional deployment will hit exactly
when things are already going wrong (full disk, power loss).

## Symptom

Two distinct failure paths, same root:

1. **Request path.** `store.get(...)` and `store.put(...)` in
   `convert_endpoint` (`api.py`) and the `SharedDescriptionCache` calls inside
   the pipeline have no error isolation. Any `sqlite3.OperationalError` —
   disk full, database locked beyond the 10 s busy timeout, corrupt page —
   propagates and the request answers 500. The worst case is `put`: it runs
   *after* a successful conversion, so every vision-model call has already been
   paid for, and the finished result is thrown away with an error.

2. **Boot path.** `create_app` constructs `CacheStore` directly; its
   `__init__` opens the database and runs the schema script. A corrupt
   `cache.sqlite3` (crash mid-write, disk full during WAL checkpoint) raises,
   `create_app` fails, and the server refuses to start — a *cache* holds the
   service down.

Repro (boot path): truncate `cache.sqlite3` to a few bytes while the service is
stopped, start it → startup exception. Repro (request path): fill the volume the
cache lives on, convert a fresh document → conversion succeeds upstream, client
gets 500.

## Measurement

Rows R1–R3 of the cache scorecard: run
`scripts/cache_bench/bench.py` and diff against the committed baseline
(`scripts/cache_bench/BASELINE.md`, same machine). The ticket is done when its
rows flip to their targets with no regression in the others.

## Root cause

The cache is treated as infrastructure that must work, not as an optional
accelerator that may fail. Nothing between the endpoint/pipeline and SQLite
distinguishes "cache unavailable" from "conversion failed", so cache errors
inherit the fail-loud handling meant for real pipeline faults.

## Impact

- A transient or environmental cache fault (full disk is the classic) turns
  every conversion into a 500 even though the pipeline is healthy — and burns
  the LLM spend of each attempt.
- A corrupt cache file causes a hard outage that requires manual intervention
  (delete the file), instead of a self-healing restart.
- Operators cannot tell from the outside that the cache is degraded — there is
  no signal separating "slow because cold" from "erroring on every access".

## Options

1. **Isolate + degrade loudly (request path), quarantine + recreate (boot
   path).** Wrap every store access so a cache exception is logged at ERROR
   (fail *loud* — visible, counted, never swallowed) and the request proceeds
   cache-less; on boot, detect a corrupt/unopenable database, rename it to
   `cache.sqlite3.corrupt-<timestamp>`, create a fresh one, and log ERROR.
   Expose a `degraded`/error counter in `/v1/cache/stats` so the condition is
   observable. Honours both principles: the failure is loud, but the blast
   radius is the cache, not the request.
2. **Circuit breaker on top of option 1.** After N consecutive cache errors,
   stop touching the store for a cool-down (log the trip). Avoids paying a 10 s
   busy timeout per request while the volume is full. More moving parts; only
   worth it if the per-request penalty of a broken cache proves painful.
3. **Status quo, documented.** Declare the cache load-bearing and require an
   operator runbook (delete the file on corruption). Rejected by the premise:
   a cache that can take down conversions is a liability in any professional
   deployment.

Option 1 is the floor; option 2 can come later, data permitting.

## Acceptance criteria

- [ ] A cache `get`/`put` failure (request path, both document and shared
      description caches) never fails the request: the conversion runs/serves
      without cache, and the failure is logged at ERROR and counted.
- [ ] A corrupt or unopenable `cache.sqlite3` at startup is quarantined
      (renamed, kept for inspection), a fresh store is created, an ERROR log
      names what happened — and the service starts.
- [ ] `/v1/cache/stats` exposes a cache-error counter so a degraded cache is
      visible without log access.
- [ ] Tests cover: put failure after successful conversion (request still
      succeeds, result returned), get failure (request converts as a miss),
      corrupt file at boot (service starts, file quarantined).
- [ ] No silent degradation: every degraded path emits exactly the loud signal
      it is supposed to (assert on logs/counters in the tests).
