# T-040: Improve diagram-detection recall (XObject-aware + tunable page gate)

**Status:** Closed — **invalid** (2026-06-24). Filed on a measurement error and
withdrawn after verification; no fix shipped.
**Priority:** High — filed as a recall gap, withdrawn before any work shipped.

## Why it was closed

T-040 was created from a first-pass [T-035](T-035-diagram-detection-recall-unmeasured.md)
result that reported 67 % recall with two "Form XObject" misses on the Transformer
paper (Fig 1/Fig 2). On taking this ticket, the very first investigation step —
`page.get_xobjects()` / `get_image_info()` on those pages — showed there are **no
Form XObjects**: the architecture and attention figures *look* vector but are
embedded as **raster images** (`get_image_info()` returns 1–2 images per page).
They are handled by the image path (`images.py`), and `extract_images_from_page`
does extract them, so they are described, not lost.

The corrected bench reports **100 % diagram recall (4/4) and 100 % figure recall
(9/9)** — no under-detection on the measured genres. There is no XObject-visibility
bug and no evidence that `MIN_DRAWINGS_PER_PAGE` drops a genuine vector figure, so
the proposed fix (XObject-aware detection + lower gate) would solve a non-problem
and only risk new false positives. Bench-before-code did its job.

## If under-detection is ever found

Re-open with a concrete case: a genre where a genuinely **vector** figure (non-zero
`get_drawings()`, not a raster image) is missed. Then the original options —
XObject-aware detection and/or a bench-tuned, precision-checked page gate — apply.
Until such a case exists, there is nothing to fix.
