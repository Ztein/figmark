# T-040: Improve diagram-detection recall (XObject-aware + tunable page gate)

**Status:** Open
**Priority:** High — silent figure loss on non-central-bank genres (quantified)
**Parent / source:** [T-035](T-035-diagram-detection-recall-unmeasured.md) measured
the gap; this ticket fixes it.

## Symptom

The recall bench ([scripts/recall_bench/bench.py](../../scripts/recall_bench/bench.py))
measures **67 % diagram-detection recall (4/6)** across two non-central-bank genres.
Two real vector figures in the Transformer paper are missed entirely (p3, p4) —
silently dropped, contrary to the project's "described, not dropped" promise.

## Root cause

Two independent gaps, both inherited from calibrating the detector on matplotlib
central-bank charts (see [diagrams.py](../../src/figmark/diagrams.py)):

1. **Vector content inside a Form XObject is invisible.** `page.get_drawings()`
   does not recurse into Form XObjects, so a figure included as a vector PDF/TikZ
   `\includegraphics` (Fig 1, the Transformer architecture) reports **0 drawings**
   and the page is never examined.
2. **`MIN_DRAWINGS_PER_PAGE=30` is too high** for sparse vector figures (Fig 2
   surfaces ~8 drawings → page skipped).

## Options

1. **XObject-aware detection** — detect Form XObject invocations (`Do` operators)
   whose referenced object is vector content, and treat their placement rectangles
   as candidate diagram regions (or render+inspect them). Fixes cause (1).
2. **Lower / make-configurable the page + cluster gates** (`MIN_DRAWINGS_PER_PAGE`,
   `MIN_DRAWINGS_PER_CLUSTER`) — fixes cause (2); also ties into the v0.2
   config-driven plan. Must be re-benched for precision (lowering gates risks new
   false positives on text pages).
3. **Both** — required to close the recall gap without regressing precision.

Recommendation: **Option 3**, re-running the recall bench *and* the precision check
(the central-bank eval) after each change so recall rises without precision falling.

## Acceptance criteria

- [ ] Recall on the T-035 bench rises (target: catch Fig 1 + Fig 2 → 6/6) with no
      new false positives on the central-bank precision check.
- [ ] Form XObject vector figures are detected (a regression test on the Transformer
      architecture page).
- [ ] Any threshold change is bench-justified and recorded (numbers in the PR).
