# T-073: Concurrent uploads of the same document each run a full conversion — the cache does not coalesce in-flight requests

**Status:** Open
**Priority:** High — this is the single most expensive gap in the cache design:
N simultaneous uploads of one document cost N full vision-model runs. The
scenario is not exotic; it is exactly what happens in an organisation when a
report is mailed out and several people (or a batch RAG ingest) upload it at
once.

## Symptom

`convert_endpoint` checks the document cache, and on a miss runs the full
conversion, `put`ting the result afterwards. There is no notion of "this
document is already being converted right now":

```
request A: get(doc-X) → miss → convert (30–300 s of LLM calls) → put
request B: get(doc-X) → miss (A not done yet) → convert again → put (overwrites)
```

Every request that arrives between A's miss and A's put repeats the entire
pipeline. The description-level cache dedupes repeated images *within* one run
(`pending_image_jobs`) and reuses descriptions across *completed* runs (T-061),
but two conversions racing each other mostly miss both layers — descriptions are
only shared once written.

## Root cause

The cache knows two states, hit and miss. A production cache in front of an
expensive computation needs a third: **in flight** — first requester computes,
subsequent requesters for the same key wait for that result instead of
recomputing (single-flight / request coalescing).

## Impact

- Direct, linear LLM cost multiplication for the most common organisational
  usage pattern (same document, many consumers, same time window).
- The duplicate conversions also occupy worker slots (`max_concurrent_jobs`),
  so unrelated users get 429s while the service burns money computing the same
  answer twice (interacts with T-069's queue: duplicates would sit in the queue
  holding upload bytes).

## Options

1. **In-process single-flight keyed on the document cache key.** A dict of
   `asyncio` events/futures per key: the first miss inserts a marker and
   converts; followers await the future and serve the cached result (or convert
   themselves if the leader failed — no error caching). Matches the current
   deployment shape (one process); a few dozen lines, no new dependency.
   Followers must respect `request_timeout_seconds` while waiting, and a
   leader crash must wake followers (try/finally around the marker).
2. **SQLite-backed in-flight claims.** A `claims` table with a heartbeat, so
   coalescing also works across processes. Only pays off if the service ever
   runs multiple workers against one cache volume — which the current design
   does not (single uvicorn process); the claim/heartbeat/stale-claim logic is
   real complexity.
3. **Do nothing; rely on T-069's queue + serial default.** With
   `max_concurrent_jobs=1` the duplicates serialise, and the second request
   *does* hit the cache once the first finishes… but only if it survives the
   429/queue in between, and any concurrency > 1 reopens the hole. Not a
   design, an accident of today's defaults.

Option 1 now; revisit option 2 only if multi-process serving becomes real.

## Acceptance criteria

- [ ] Two concurrent conversions of the same document result in **one**
      pipeline run; the second request returns the same result, marked as
      served from cache (header/`cached` flag may distinguish "coalesced").
- [ ] A failed leader does not poison followers: they either run the
      conversion themselves or receive the leader's error — never hang, and
      failures are never cached.
- [ ] Waiting followers still honour `request_timeout_seconds`.
- [ ] Different documents (different digests) are never coalesced; different
      config fingerprints for the same document are never coalesced.
- [ ] A test drives ≥ 2 concurrent uploads of one document against the mockllm
      server and asserts exactly one conversion's worth of upstream calls.
