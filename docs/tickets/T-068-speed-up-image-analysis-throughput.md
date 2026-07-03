# T-068: Image/figure analysis is slow end-to-end — measure the bottlenecks and decide how to speed it up

**Status:** Open
**Priority:** Medium — description latency dominates wall-clock on figure-heavy
documents (a chartbook can carry 60–90 figures), and it is the cost/time the
downstream consumer feels most.

## Symptom

Converting a figure-heavy document is dominated by vision-model calls. On the
office-eval / eval corpora a single description call has been observed anywhere
from ~0.5 s to 60–90 s depending on endpoint load, and documents carry dozens of
figures. Users experience figmark as "slow on the interesting documents."

## What already exists (don't rebuild it)

- **Within-document figure descriptions already run in parallel.** The pipeline
  gathers every image/diagram into `Job`s and runs them on a
  `ThreadPoolExecutor` at `concurrency.max_workers` (default **8**) —
  `run_jobs` in `parallel.py`. So "run multiple parallel requests" is *already
  done* for the figure batch; the question is whether 8 is the right number and
  where the *non*-parallel time goes.
- **Descriptions are cached** on disk / cross-request (T-061), so re-runs only
  pay for new figures.

## Suspected bottlenecks (to confirm by measurement, not assumption)

- **Serial calls on the critical path.** `detect_language` and
  `summarize_document` are two separate blocking `completions.create` calls that
  run *before* the parallel figure batch (`pipeline.convert`), one after the
  other. On a slow endpoint these two alone can add a minute+ of pure serial
  latency to every document, no matter how parallel the figures are.
- **Concurrency ceiling.** `max_workers=8` — is the endpoint's real limit higher
  or lower? Too low leaves throughput on the table; too high may trigger
  rate-limits/timeouts (the 60–90 s tail).
- **Per-call latency, not just count.** Some calls take 60–90 s. If that is
  large-image processing time, more resize/downscale (T-022 path) may cut it; if
  it is endpoint queueing, concurrency tuning is the lever instead.
- **Server-level single-document gate.** The HTTP service's
  `max_concurrent_jobs` defaults to **1** — one document at a time; a second
  request gets 429. Fine for a single-tenant box, but it means no cross-document
  overlap even when the endpoint has spare capacity.
- **No request batching / connection reuse review.** Whether the OpenAI client
  reuses connections, and whether the endpoint supports multi-image or batched
  requests, is unmeasured.

## Options (analysis first — bench before code)

1. **Instrument and profile.** Record, per document: total wall-clock, time in
   language+summary vs the figure batch, per-call latency distribution, worker
   utilisation. This is the prerequisite — it tells us which lever below actually
   pays. Nothing else should ship without these numbers.
2. **Overlap the serial calls.** Run `detect_language` and `summarize_document`
   concurrently with each other, and/or fold them into the parallel batch so the
   figure work starts immediately. Removes serial latency from the critical path.
3. **Tune / make `max_workers` adaptive.** Sweep the concurrency level against
   the real endpoint; consider backing off on rate-limit signals instead of a
   fixed 8.
4. **Cut per-call cost.** Revisit resize/quality for the largest images if
   profiling shows call time scales with payload size.
5. **Cross-document concurrency (service).** Allow `max_concurrent_jobs > 1`
   where the endpoint has headroom, so a queue of documents overlaps — bounded
   so it doesn't fight the per-document workers for the same rate limit.
6. **Batching / multi-image requests**, if the endpoint supports it — fewer
   round-trips for many small figures.

## Impact

- Faster conversions on exactly the documents figmark is *for* (figure-heavy
  reports), and better use of a paid endpoint's capacity.
- Some levers (2, 5) also reduce the blast radius of a slow endpoint, which today
  can time out the whole run (a serial summary call over the 60 s client timeout
  fails the document — observed 2026-07-03).

## Acceptance criteria

- [ ] A measured profile of where conversion time goes on a figure-heavy
      document (serial vs parallel, per-call distribution, worker utilisation) —
      recorded, so the decision is data-driven.
- [ ] A recorded decision on which lever(s) to pursue, with expected/observed
      speedup, gated by that profile (bench before code).
- [ ] Any concurrency change is validated against the real endpoint for
      rate-limit / timeout behaviour, not just happy-path wall-clock.
