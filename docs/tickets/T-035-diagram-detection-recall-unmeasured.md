# T-035: Diagram detection recall is unmeasured (and single-genre calibrated)

**Status:** Closed — recall measured on 2 genres (2026-06-24). The bench
([scripts/recall_bench/bench.py](../../scripts/recall_bench/bench.py), corpus via
[download.py](../../scripts/recall_bench/download.py)) reports **67 % overall
recall (4/6)**: U-Net paper 1/1, Transformer paper 3/5. The two misses pin down the
real causes (below), and the fix is split into [T-040](T-040-diagram-recall-fix.md).
This ticket — *measure* recall — is done.
**Priority:** High — the most dangerous blind spot: silent figure loss
**Source:** External code review (2026-06-24), verified against the code.

## Result (2026-06-24)

| Genre | Doc | Recall | Misses |
|---|---|---|---|
| Scientific paper (LaTeX) | U-Net (Ronneberger et al.) | 1/1 | — |
| ML paper (TikZ + attention) | Transformer (Vaswani et al.) | **3/5** | p3, p4 |
| | | **4/6 = 67 %** | |

**Two distinct root causes, both from matplotlib-genre calibration:**
1. **Vector content in a Form XObject is invisible.** Fig 1 (the Transformer
   architecture) is a vector figure, but `page.get_drawings()` returns **0** on
   that page — the paths live inside a Form XObject that `get_drawings()` does not
   recurse into — so the page is never examined. A pure-threshold tweak can't fix
   this; detection must look inside XObjects (or use a different signal).
2. **`MIN_DRAWINGS_PER_PAGE=30` is too high for sparse vector figures.** Fig 2
   surfaces only ~8 drawings, below the gate, so the page is skipped.

**Decision (acceptance #3):** making the constants config-driven helps cause (2)
but **not** (1), which is a code-visibility bug, not a tuning value. So the answer
is "config-driven alone is insufficient" — the fix needs both a code change
(XObject-aware detection) and a tuned/lower page gate. That work is
[T-040](T-040-diagram-recall-fix.md).

## Symptom

The 31-document eval quantifies *false positives* (~2 % logos described as
diagrams) but never *false negatives* — how many real vector diagrams the
clustering missed entirely. The whole of [diagrams.py](../../src/figmark/diagrams.py)
rests on constants that are, by the module's own comment
([diagrams.py:22-25](../../src/figmark/diagrams.py)), "empirically calibrated
against a central-bank monetary-policy report": `MIN_DRAWINGS_PER_PAGE=30`,
`MIN_DRAWINGS_PER_CLUSTER=8`, and the size/merge thresholds around them.

## Root cause

No recall measurement, and a single-genre calibration. On other document genres
(InDesign brochures, TikZ figures, CAD, two-column scientific papers) these
thresholds likely tip into **silent under-detection** — a page with few drawing ops
never gets examined at all (`< MIN_DRAWINGS_PER_PAGE` returns early).

## Impact

A missed figure breaks the project's core promise ("described, not dropped"), and
it is undetectable without ground truth. Independently corroborated by the table
work ([T-026](T-026-tables-flattened-to-text.md) /
[T-030](T-030-labelled-table-bench.md)): the pipeline was overfit to one
central-bank document, and only a broader corpus exposed it.

## Options

1. **Build a small recall bench** — hand-annotate ground-truth figure regions on
   ≥2 non-central-bank genres, measure detection recall, and report it alongside
   precision (mirror the labelled-bench approach used for tables in T-030).
2. **Make the clustering constants config-driven** so a new genre can be tuned
   without code edits (ties into the v0.2 config-driven pipeline plan).
3. Both.

Recommendation: **Option 1 first** (measure recall honestly), then Option 2 if
recall proves genre-sensitive.

## Acceptance criteria

- [x] Detection recall reported on ≥2 genres outside the central-bank corpus, against
      hand-annotated ground-truth figure regions. — 67 % (4/6); see Result above.
- [x] Missed-figure cases are documented with the threshold(s) responsible. —
      Form XObject invisibility + `MIN_DRAWINGS_PER_PAGE`.
- [x] A decision is recorded on whether the clustering constants must become
      configurable (and if so, which). — config-driven alone is insufficient; the
      fix needs XObject-aware detection too. Tracked in T-040.
