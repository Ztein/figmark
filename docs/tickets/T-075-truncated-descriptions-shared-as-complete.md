# T-075: A truncated figure description is stored in the shared cross-request cache as if complete

**Status:** Closed — **Option 1 shipped 2026-07-06** (a `.truncated` sidecar
marker written by `describe_image`/`describe_diagram` keeps token-capped
descriptions out of the shared cross-request cache; the skip is logged, the
partial still serves its own document per T-033, and the next document
regenerates; scorecard row Q1 PASS).
**Priority:** Low — the warning exists and a partial description still beats a
dropped figure (product thesis), but the shared cache silently *promotes* a
known-degraded result into every future document that contains the same figure,
for the full TTL.

## Symptom

When the vision model stops at the token cap, `describe.py` detects
`finish_reason == "length"`, warns loudly ("may be cut mid-sentence"), keeps
the text (deliberate, T-033) — and writes it to the per-document description
file. With the cross-request cache enabled, `_with_shared_put` in
`pipeline.py` then also writes that same truncated text into the **shared**
store, where `SharedDescriptionCache.get` serves it to *other* documents and
*later* requests with no warning at all: the T-033 log line fires only on the
request that generated the description.

So the fail-loud contract holds for the first request and silently degrades
for every subsequent one that reuses the entry — the situation T-024/T-033
exist to prevent.

## Measurement

Rows Q1 of the cache scorecard: run
`scripts/cache_bench/bench.py` and diff against the committed baseline
(`scripts/cache_bench/BASELINE.md`, same machine). The ticket is done when its
rows flip to their targets with no regression in the others.

## Root cause

The shared-cache write path (`_with_shared_put`) has no notion of description
*quality*: `on_done` receives only the text, not the fact that generation hit
the token cap. Anything non-empty is cached globally as equally good.

## Impact

- A single token-capped generation becomes the canonical description of that
  figure for up to `max_age_hours` (and indefinitely under LRU re-stamping if
  the figure is hot — e.g. a company template diagram appearing in many
  documents).
- Downstream consumers (RAG chunks, assistant context) repeatedly ingest a
  mid-sentence artefact, and no log or counter on those requests says so.

## Options

1. **Don't share partials.** Keep T-033's per-request behaviour (use the
   truncated text for *this* document, warn) but skip the shared-cache `put`
   when `finish_reason == "length"`; the next document regenerates, likely
   completing. Smallest change; costs an occasional extra vision call —
   exactly the case where paying again is justified.
2. **Share, but marked.** Store a completeness flag alongside the text
   (payload envelope or key suffix); on a shared hit of a partial, log the
   same loud warning and count it in stats. Preserves maximum reuse and the
   fail-loud contract, but adds a payload format to the store and still
   propagates the artefact.
3. **Retry at generation time.** On `finish_reason == "length"`, retry once
   with a higher cap or a "be concise" nudge before accepting the partial.
   Attacks the source, but changes generation behaviour and cost for a case
   T-033 already decided to tolerate; independent of the cache question.

Option 1 is the proportionate fix; option 3 can be a separate consideration if
truncation turns out to be common in practice (worth a counter either way).

## Acceptance criteria

- [x] A description generated with `finish_reason == "length"` is **not**
      served from the shared cross-request cache to a different request
      *silently* — either it is never stored there (option 1) or every shared
      hit of it is as loud as the original generation (option 2).
- [x] The chosen behaviour is covered by a test that fakes a length-capped
      completion and asserts the shared-cache contents / logging.
- [x] Truncation events are countable (log-derivable or a stats counter), so
      "how often does this happen" stops being guesswork.
