# T-035: Diagram detection recall is unmeasured (and single-genre calibrated)

**Status:** Open
**Priority:** High — the most dangerous blind spot: silent figure loss
**Source:** External code review (2026-06-24), verified against the code.

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

- [ ] Detection recall reported on ≥2 genres outside the central-bank corpus, against
      hand-annotated ground-truth figure regions.
- [ ] Missed-figure cases are documented with the threshold(s) responsible.
- [ ] A decision is recorded on whether the clustering constants must become
      configurable (and if so, which).
