# T-037: O(n²) drawing clustering is a hotspot on draw-heavy pages

**Status:** Open
**Priority:** Low — performance, not correctness; profile before optimising
**Source:** External code review (2026-06-24), verified against the code.

## Symptom

`_cluster_rects` ([diagrams.py:72-96](../../src/figmark/diagrams.py)) does a
pairwise proximity test in a nested loop over every drawing rectangle on the page.
The union-find itself is near-linear, but the pair scan that feeds it is O(n²).

## Root cause

All-pairs `_close()` comparison before the union step.

## Impact

On the heaviest pages (e.g. some BIS documents with thousands of vector operations
per page) this is a real latency hotspot. It is not a correctness issue — output is
unaffected — so priority is low until profiling shows it matters.

## Options

1. **Spatial grid bucketing** — bin rects into cells, test only rects in
   neighbouring cells. Simplest route to near-linear.
2. Sweep-line over x with an active-interval set.
3. Leave as-is until a profile flags it as a real bottleneck.

Recommendation: profile a heavy page first; if it is hot, Option 1.

## Acceptance criteria

- [ ] Clustering is near-linear on a draw-heavy page, with **identical** region
      output to the current implementation (regression-checked).
- [ ] A before/after timing on a heavy page is recorded.
