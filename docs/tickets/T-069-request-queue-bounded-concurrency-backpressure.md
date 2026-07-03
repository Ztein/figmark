# T-069: The service has no request queue — it rejects the moment all worker slots are busy, instead of queueing with bounded backpressure

**Status:** Open
**Priority:** Medium — single-tenant deployments cope today via client-side
retry, but any bursty consumer (a RAG pipeline ingesting a batch) hits a wall of
immediate rejections with no way to hand figmark a short queue of work.

## Symptom

Concurrency control on the HTTP surface is a bare semaphore with a
reject-if-busy pre-check (`api.py`, shared `run_conversion`):

```python
sem = app.state.job_semaphore              # asyncio.Semaphore(max_concurrent_jobs)
if sem.locked():                           # no permits left → reject immediately
    raise HTTPException(429, "Server busy — too many conversions")
async with sem:
    ...  # run the conversion
```

with `max_concurrent_jobs` defaulting to **1**. So:

- There is **no queue**. A request that arrives while all worker slots are busy
  is rejected *instantly* with 429 — it cannot wait for a slot, even briefly.
- With the default of 1, the service is effectively serial: the second
  overlapping request is always rejected.
- The client is left to implement its own retry/backoff to get work done — the
  service offers no "accept a few, queue them, reject only when the queue is
  also full" behaviour.
- Minor correctness nit: `sem.locked()` and the `async with sem` acquire are not
  atomic (a TOCTOU window), so the reject decision and the actual admission can
  disagree under load.

## Root cause

The design admits work with a semaphore gate, not a queue + worker pool. A
semaphore bounds *concurrency* but has no notion of a *waiting line* with a
depth limit, so the only two states are "run now" or "rejected" — there is no
"queued, will run soon" state and therefore no place to apply bounded
backpressure.

## What we want (the ask)

Three knobs, explicitly:

1. **Bounded parallelism** — run up to *N* conversions at once (the existing
   `max_concurrent_jobs`, but as real workers draining a queue).
2. **A bounded queue** — accept up to *Q* additional jobs to wait for a worker.
3. **Backpressure** — when the queue is already full, reject the new job loudly
   ("too many in queue, can't enqueue another") rather than accepting unbounded
   work or blocking forever.

## Considerations (design must address)

- **Request lifetime vs queue wait.** `/v1/convert` is synchronous — the client
  holds the connection for the result. A queued job still has to finish inside
  the client's (and the server's `request_timeout_seconds`) timeout, and the
  queue wait *eats into* that budget. Either the wait counts against the
  timeout (and is surfaced), or the API moves to submit-then-poll (Option 2).
- **The reject must be honest and actionable** — a 429 (or 503) with a
  `Retry-After` header and a body that distinguishes "workers busy, queue full"
  from other errors. Never a silent drop or an unbounded hang (fail-loud, T-024).
- **Fairness** — FIFO so a job can't starve; no reordering that lets late
  arrivals jump the line.
- **Memory** — queued uploads hold bytes; the queue depth *Q* bounds worst-case
  memory, which is why it must be bounded, not unbounded.
- **Observability** — queue depth, current wait time, and reject count belong in
  the metrics surface (same spirit as the cache telemetry, T-064), so an
  operator can size *N*/*Q* from data.
- **Graceful shutdown** — draining in-flight + queued work on stop, not dropping
  it.
- **Interaction with T-068** — that ticket lists "cross-document concurrency
  (service)" as a speed lever; this ticket is the *mechanism* for it. Raising
  *N* only helps if the vision endpoint has headroom (per-document workers
  already consume the rate limit), so *N* and the per-document `max_workers`
  must be reasoned about together, not tuned in isolation.

## Options

1. **Bounded async queue + fixed worker pool, still synchronous.** An
   `asyncio.Queue(maxsize=Q)` fronted by *N* worker tasks; `run_conversion`
   enqueues (or 429s if full) and awaits its result. Smallest change to the
   contract — clients still call `/v1/convert` and get the Markdown back — with
   real queueing and backpressure. The queue wait must be bounded and counted
   against the timeout.
2. **Asynchronous job API.** `POST` returns a job id immediately; the client
   polls `GET /v1/jobs/{id}` (or a webhook) for the result. Decouples request
   lifetime from conversion time — the right shape for long/bursty batch work
   and large documents — but a bigger contract change and new state to manage.
   May not fit the Mistral-OCR compat surface (T-052), which is call-and-wait.
3. **Just raise `max_concurrent_jobs`.** Increases parallelism but adds no
   queue and no backpressure semantics — the N+1th request still gets an
   instant reject. Not a solution to the ask; only a stopgap knob.

Option 1 is the natural next step for the current synchronous contract; Option 2
is worth it if batch/long-job consumers become a real use case.

## Acceptance criteria

- [ ] Configurable **worker count** (*N*) and **queue depth** (*Q*), with
      documented defaults that keep the single-tenant behaviour sane.
- [ ] A job that arrives with workers busy but the queue not full **waits** and
      runs; a job that arrives with the queue full is **rejected loudly** (429/503
      + `Retry-After`, a body naming the condition) — never dropped or hung.
- [ ] The queue wait is bounded and interacts correctly with
      `request_timeout_seconds` (a job that would exceed the client's budget is
      surfaced, not silently timed out mid-queue).
- [ ] Queue depth / wait / reject metrics are exposed for sizing *N*/*Q*.
- [ ] Tests cover: N concurrent admitted, up to Q queued and drained in order,
      and the full-queue rejection.
- [ ] The TOCTOU reject/admit race is gone (admission is atomic with enqueue).
