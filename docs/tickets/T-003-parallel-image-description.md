# T-003: Parallel processing of image and chart descriptions

**Status:** Closed — implemented 2026-05-20 via ThreadPoolExecutor + rich Live view
**Priority:** Medium — time saving, not a functionality fix
**Requested:** 2026-05-20

## Resolution

Implemented in [src/figmark/parallel.py](../../src/figmark/parallel.py). The pipeline now
collects cache misses from both image and chart descriptions into a list of `Job`s and
submits them to a ThreadPoolExecutor with configurable parallelism.

The CLI builds a `rich.Live` view that shows:
- A header row with progress bar, percent, done/total, elapsed time, ETA
- A table of in-flight calls with a running second timer
- A table of the 5 most recently finished calls with their runtime
- A final summary with average time and measured speedup

Configurable via `concurrency.max_workers` (default 4) in [config.example.yaml](../../config.example.yaml).

Verified live: [test_pipeline_determinism_workers_1_vs_4](../../tests/test_pipeline.py)
runs the same mini-PDF twice (1 worker + 4 workers) and verifies that
`<name>.md` is byte-for-byte identical.

## Symptom / motivation

Running against `penningpolitisk-rapport-mars-2026.pdf` (~30 images+charts) takes 3-5 minutes. Each API call to Gemma is 5-15 seconds. The calls run sequentially — each call blocks until the previous one is done — even though almost all of the time is I/O wait. With reasonable parallelism we can get the time down to ~1 minute.

```
Current:    [###] [###] [###] [###] [###] [###]  → 30 * 8s = 4 min
Parallel:   [###]  → max 8s * (30/N) batches
            [###]
            [###]
            [###]
```

The CLI output is also monotonous today (`page X: filename → API`); it doesn't get much nicer when 30 lines arrive in a row.

## Requirements

1. **Configurable number of concurrent API calls** via `config.yaml`. A sensible default — maybe 4 or 6 — so we don't hit Berget's rate limits unintentionally.
2. **Applies to both images AND charts** — a shared parallel pool for all `describe_image` and `describe_diagram` calls.
3. **A nice CLI view** during the run: progress bar, done/total count, what's running right now, ETA. Not spammy.
4. **Cache keeps working** — if all descriptions are already cached, parallelism should not kick in at all.
5. **Fail loudly** — if a worker fails, the error should be reported clearly with which image/chart it concerned. Preferably abort the whole run so we don't lose errors in the noise.
6. **Deterministic output** — `raw_text.txt` and `<name>.md` should look identical regardless of worker count or execution order.

## Options

### Option 1: ThreadPoolExecutor + tqdm
`concurrent.futures.ThreadPoolExecutor` with N workers, `tqdm.tqdm` for the progress bar.

- ✅ Simple — the OpenAI SDK is thread-safe (HTTP calls)
- ✅ tqdm is minimal, well-proven, integrates well
- ✅ Existing retry logic in `describe.py` and `diagrams.py` works unchanged
- ❌ tqdm output is functional but not "wow-nice"

### Option 2: ThreadPoolExecutor + rich
`rich.progress` for an advanced progress view with a live-updated table ("3 running now: image X, chart Y, ...").

- ✅ Nicest in the CLI — colors, live table, ETA, spinner
- ✅ Same underlying threading as Option 1
- ❌ Adds `rich` as a dependency (~1 MB)
- ❌ A bit more code to set up Progress + Task per call

### Option 3: asyncio + httpx + AsyncOpenAI
A fully async pipeline. Rewrite `describe_image`, `describe_diagram`, `main.run` to async.

- ✅ More "modern Python"
- ✅ Scales well if we ever want even more concurrency
- ❌ Big refactor — main.run, tests, everything becomes async
- ❌ A ThreadPool is plenty for I/O-bound work with dozens of calls
- ❌ Complicates the test code unnecessarily

### Option 4: Keep it sequential
- ✅ No code changes
- ❌ Slow for large documents

## Recommendation

**Option 2 (ThreadPoolExecutor + rich).** A nice CLI is a stated requirement. Rich is the industry standard for CLI UI in Python, well maintained, and not large. Threading is enough for I/O-bound work with ~30-50 concurrent calls.

## Suggested config fields

```yaml
concurrency:
  # Number of concurrent API calls for description. Berget typically tolerates 4-8
  # without rate-limiting. Set higher at your own risk.
  max_workers: 4
  # Abort the whole run on the first error (the alternative is to collect errors and
  # report at the end — but "fail loudly" says abort).
  fail_fast: true
```

## Suggested CLI view

```
Describing 30 images and charts via google/gemma-4-31B-it
Elapsed: 0:01:23 • Remaining: ~0:00:42

[#############-------]  60%   18/30 done   4 running now

  ↻ page 11 chart 2      8.4s
  ↻ page 14 chart 1      6.1s
  ↻ page 35 image 01     3.2s
  ↻ page 68 chart 1      0.7s

  ✓ page  1 image 01     4.2s
  ✓ page  1 image 02     5.7s
  ✓ page 11 chart 1      7.8s
  ...
```

**Details:**
- **Elapsed time**: an increasing counter from the start of the description phase, formatted `H:MM:SS`
- **Remaining** (ETA): computed from the average time per finished call × remaining calls, adjusted for max_workers
- **Percent done**: large and clear on the progress bar row, both as a percentage and `done/total`
- **Active calls**: a list with a rolling second timer per in-flight call (so you can see which ones have hung)
- **Finished calls**: scrolled at the bottom with the actual runtime per call
- Live-updating with rich.Live so the whole view refreshes in place — not spamming new lines

When everything is done, a final summary:
```
Done in 0:01:42. 30 calls, average 4.5s/call, total API time 2:15 (sequentially would have taken ~2:15).
```

## Acceptance criteria

- [ ] `concurrency.max_workers` in `config.yaml`, default 4
- [ ] The monetary policy report runs at least 2× faster with max_workers=4 (measured against 1 worker)
- [ ] A live test verifies that the final output is identical for max_workers=1 and max_workers=4 (same `<name>.md` byte-for-byte after sorting)
- [ ] The CLI shows a progress bar with percent + done/total
- [ ] The CLI shows elapsed time (timer from start) + estimated remaining (ETA)
- [ ] The CLI shows a list of in-flight calls with an individual second timer
- [ ] A final summary with total time, average time per call, and total API time (sequential comparison)
- [ ] An error in a worker triggers a clear fail-loudly message and aborts the rest
- [ ] The cache path activates before worker startup if all descriptions already exist on disk
- [ ] README updated

## Things to keep in mind during implementation

- **Rate limits:** Berget can return 429. The existing retry logic in `describe.py` with exponential backoff works unchanged — but with several concurrent calls we may trigger more 429s. Watch.
- **Thread vs process safety:** The `OpenAI` client is thread-safe (HTTP calls via httpx, no shared mutable state). Good.
- **Cache race:** Two threads can start on the same image if both check the cache first. For correctness this is no problem (deterministic file writes, will be overwritten with the same result). We should read the cache **before** scheduling a worker so we save a call.
- **Output order:** `assemble()` runs after all calls are done, so the final file is deterministic even if the calls finish in a different order.
