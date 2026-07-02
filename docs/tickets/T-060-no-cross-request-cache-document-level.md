# T-060: The HTTP surface re-converts identical documents from scratch — no cross-request cache

**Status:** Open
**Priority:** High — every repeated upload of the same document (re-upload in a
new chat, RAG re-ingestion, retries) re-runs the full pipeline and re-spends the
full vision-model cost. The pipeline's own disk cache exists but is written into
a per-request temp dir and deleted in `finally`, so over HTTP it never hits.

## Symptom

Upload the same PDF to `/v1/convert` (or `/v1/ocr`) twice: both requests take
the full pipeline time and make the full set of vision-model calls. The
description/language/summary caches (T-034) are created and destroyed inside
each request's `tempfile.mkdtemp(...)` → `shutil.rmtree(...)` lifecycle
([api.py](../../src/figmark/api.py), [ocr_compat.py](../../src/figmark/ocr_compat.py)).
From an API consumer's perspective figmark has no cache at all.

## Root cause

The caches were designed for CLI runs, where `output/<name>/` persists between
invocations. The API surfaces reuse the pipeline but give it throwaway storage.

## Decided design (2026-07-02)

A **document-level result cache**, plus shared infrastructure that T-061 (the
shared description cache) also rides on:

1. **Key:** content digest of the uploaded bytes + the config fingerprint
   (T-034 semantics: model/prompt/language/gate changes must miss) + the
   figmark version (output format evolves). **Value:** the full conversion
   result needed to serve a response (markdown, per-page split, counts,
   language, usage of the original run).
2. **Size cap:** a configurable maximum cache size; when exceeded, the
   least-recently-used entries are evicted until under the cap.
3. **LRU semantics:** every entry carries a last-accessed timestamp; a cache
   hit re-stamps the entry to "now" (it becomes the youngest).
4. **Max age:** a configurable TTL in hours; entries older than it (by
   last-accessed time) are expired.
5. **Targeted removal:** a method to remove a single document from the cache
   (by its document digest).
6. **Full clear:** a method to empty the entire cache.

## Options (for the open implementation choices — the design above is decided)

1. **Store layout:** one directory per entry under a configurable cache root,
   with a small index (JSON/SQLite) for size + last-accessed bookkeeping.
   SQLite gives atomic LRU updates under concurrent requests; a JSON index is
   simpler but needs a lock. Either must survive process restarts.
2. **Management surface:** admin HTTP endpoints (e.g. `DELETE /v1/cache/{digest}`,
   `DELETE /v1/cache`, `GET /v1/cache/stats`) behind the existing bearer auth,
   and/or a CLI subcommand. HTTP fits the service deployment; pick at
   implementation time.
3. **Hit accounting:** a cached response should say so (e.g. a `cached: true`
   field or `X-Figmark-Cache: hit` header) and report zero new API calls —
   never re-report the original run's token usage as if it were fresh spend
   without labelling it. Fail-loud/honesty applies to caching too.

## Notes / constraints

- **Data at rest:** caching means document-derived content persists server-side
  beyond the request. Document this clearly (deployment docs + README); the
  TTL, size cap, and clear method are also the operator's privacy controls.
- **Deployment:** the hardened compose mounts the work dir as tmpfs (read-only
  rootfs). A persistent cache needs a dedicated volume; without one the cache
  is per-uptime — acceptable, but the docs must say which one you get.
- **Concurrency:** two simultaneous uploads of the same new document should not
  corrupt the store (last-writer-wins on identical content is fine).
- Cache management endpoints are authenticated exactly like `/v1/convert`.

## Acceptance criteria

- [ ] Second upload of an identical document (same config) returns the cached
      result with no vision-model calls, on both `/v1/convert` and `/v1/ocr`,
      and the response is labelled as a cache hit.
- [ ] A config change (model/prompt/language/gates) or figmark upgrade misses
      the cache (T-034 parity).
- [ ] `input.cache` (or equivalent) config: max size + max age (hours), both
      enforced — LRU eviction on size, expiry on age, last-accessed re-stamped
      on every hit. No hidden defaults: the section is explicit.
- [ ] A single document can be removed from the cache; the whole cache can be
      cleared. Both are authenticated and covered by tests.
- [ ] Restart behaviour (persistent volume vs per-uptime tmpfs) is documented
      in the deployment docs, along with the data-at-rest implications.
- [ ] The offline suite covers: hit, config-fingerprint miss, TTL expiry,
      LRU eviction under a small cap, targeted delete, full clear.
