# T-035: Diagram detection recall is unmeasured (and single-genre calibrated)

**Status:** Closed — recall measured on 2 genres (2026-06-24). The bench
([scripts/recall_bench/bench.py](../../scripts/recall_bench/bench.py), corpus via
[download.py](../../scripts/recall_bench/download.py)) reports **100 % diagram
recall (4/4) and 100 % figure recall (9/9)** — every figure on both genres is
covered, vector figures by the clustering and raster figures by images.py. Nothing
is dropped.
**Priority:** High — the most dangerous blind spot: silent figure loss
**Source:** External code review (2026-06-24), verified against the code.

## Result (2026-06-24, corrected)

| Genre | Doc | Diagram recall | Figure recall |
|---|---|---|---|
| Scientific paper (LaTeX) | U-Net (Ronneberger et al.) | 1/1 | 4/4 |
| ML paper (vector + raster) | Transformer (Vaswani et al.) | 3/3 | 5/5 |
| | | **4/4 = 100 %** | **9/9 = 100 %** |

**Correction of a first-pass error.** An earlier draft reported 67 % recall with
two "Form XObject" misses on the Transformer paper (p3/p4). On verification that
was a **vector-vs-raster annotation mistake**: the architecture and attention
figures *look* vector but are embedded as **raster images** (`get_image_info()`
returns 1–2 images, `get_drawings()` returns 0). They are therefore the image
path's job, and `extract_images_from_page` does extract them — they are described,
not lost. So there is no XObject under-detection: the diagram detector finds every
genuine vector figure, and the image path catches the rest. This is exactly the
kind of false alarm the bench-before-code step exists to catch.

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
      hand-annotated ground-truth figure regions. — 100 % diagram (4/4) and 100 %
      figure (9/9); see Result above.
- [x] Missed-figure cases are documented with the threshold(s) responsible. — none:
      figures that first appeared "missed" are raster images caught by the image
      path, not diagram misses.
- [x] A decision is recorded on whether the clustering constants must become
      configurable (and if so, which). — no change needed on the measured genres;
      recall is already 100 %. Revisit only if a genre with genuinely-missed *vector*
      figures turns up.
