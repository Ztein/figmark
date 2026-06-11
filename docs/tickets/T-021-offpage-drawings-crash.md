# T-021: Off-page drawing clusters crash diagram rendering

**Status:** Closed — fixed 2026-06-11, found by the central-bank evaluation corpus
**Priority:** HIGH — hard crash on real-world documents

## Symptom

Both BIS Annual Economic Reports (2024, 2025) in the evaluation corpus crashed
the pipeline:

```
pymupdf.mupdf.FzErrorArgument: code=4: Invalid bandwriter header dimensions/setup
```

at `render_and_save_region` → `pix.tobytes("png")` (page 23 of bis-ar-2024).

## Root cause

The reports contain vector drawings with **negative y-coordinates** — content
placed above the page boundary (crop marks / spill-over). A dense off-page
cluster passes every cluster filter, and the bbox clamping only clamps the
*lower* bounds (`max(0, y0 - PADDING)`), so an entirely-off-page cluster came
out as e.g. `(50.2, 0.0, 523.6, -72.6)` — negative height. The page-rect
intersection produced a degenerate rect, `get_pixmap` produced a garbage-sized
pixmap, and the PNG writer threw.

## Resolution

After clipping the expanded region to the page rect in
[find_diagram_regions](../../src/figmark/diagrams.py), degenerate or sub-1px
remnants are skipped. Regression test
(`test_offpage_drawings_yield_no_degenerate_regions`) builds a synthetic page
with a filter-passing drawing cluster at negative y and asserts every returned
region has positive dimensions **and actually renders to PNG**. Verified
against both real BIS reports (full pipeline, no crash).

Worth noting: the synthetic repro required thin *rects*, not `draw_line` —
zero-height line rects are already dropped by `MIN_DRAWING_DIM`.

## Acceptance criteria

- [x] Regression test red before the fix, green after
- [x] bis-ar-2024 and bis-ar-2025 convert without errors
- [x] Existing diagram tests unaffected (calibrated page-11/68 counts unchanged)
