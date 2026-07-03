# T-055: Vector charts in LibreOffice-produced PDFs are missed by diagram detection

**Status:** Closed — **shipped 2026-07-03** (Option 2 + a table-vs-chart
discriminator, bench-first). Axis-aligned hairlines now *join* clusters but
don't gate them; a cluster needs ≥ 4 solid (non-line) members. That alone made
zebra slide tables cluster as diagrams, so a suppression step was added: a
cluster substantially overlapping a *table-like* `find_tables` candidate
(≥ 3 rows, ≥ 2 cols, ≥ 45 % filled cells — charts' grid-junk candidates
measured ≤ 36 %, real tables ≥ 50 %) is dropped — unless the candidate contains
≥ 3 sloped/curved drawings, which marks a multi-panel *chart grid* (panel
frames form a ruled "table"); real data tables measured 0 sloped members,
chart grids ≥ 3. Bench results (`scripts/lo_diagram_bench/bench.py`):
**chart recall 4/7 → 7/7, false positives 9 → 0**. The T-035 recall bench
stays 4/4 + 9/9. Eval-corpus sweep (812 draw-heavy pages): regions 760 → 1121;
gains are hairline-drawn charts (fed-fsr, cnb chartbook, bis-qr pages went
0 → 2-6); every "down" page spot-checked is a table that was wrongly described
as a diagram before (boe-mpr forecast tables, oenb/cnb data tables) or
over-segmentation now merged (a heatmap 5 → 1). Known misses, documented in
the bench: LO chart types drawn as a handful of path objects (radar ≈ 4
drawings, sunburst on a 21-drawing page) sit below the page/cluster gates.
**Priority:** High — this is figmark's headline capability (describe charts), and
the whole Office path (T-054) routes documents through LibreOffice, so *every*
chart in a converted docx/xlsx/pptx is exposed to this miss.

## Symptom

A PowerPoint slide with a plain bar chart (`poi-bar-chart.pptx` in the office-eval
corpus) converts to a PDF whose page has 34 vector drawings — clearly a chart —
but `find_diagram_regions` returns no region, so the chart is neither rendered nor
described. Only its loose text (title, axis labels) survives into the Markdown.

## Root cause

LibreOffice draws chart axes and gridlines as **axis-aligned zero-thickness
strokes**: a vertical gridline has `rect.width == 0`. The per-drawing filter in
[diagrams.py](../../src/figmark/diagrams.py) (`MIN_DRAWING_DIM = 2`) rejects a
drawing when *either* dimension is `< 2`, which was tuned to drop specks/dots in
matplotlib-style PDFs (where plotted curves are sloped, non-degenerate rects).
On the LO bar chart it discards all 27 line strokes; the 5 remaining fills (4
bars + a legend chip) are below `MIN_DRAWINGS_PER_CLUSTER = 8`, so no cluster
forms.

## Impact

- Charts in Office documents (the T-054 fidelity goal) are silently dropped from
  description — exactly the "text-only extraction" outcome the LibreOffice
  decision was meant to avoid.
- Any native PDF producer that draws axis-aligned hairlines the same way
  (LaTeX/TikZ, some BI exports) is exposed too.

## Options

1. **Count degenerate axis-aligned lines as cluster members** (`width < 2 AND
   height < 2` instead of `OR`). Simplest, but ruled/zebra-striped tables are
   made of exactly such lines + row-shading fills — they would start clustering
   as "diagrams", double-representing tables (T-031 extracts them separately)
   and burning API calls. Needs a discriminator.
2. **Lines join clusters but don't gate them**: cluster on all drawings, but
   require a minimum number of *filled* (non-line) members before a cluster
   counts as a chart. Bar/area charts pass (bars are fills); pure ruled grids
   fail (no fills). Risk: zebra-striped tables (many fills) still slip through;
   line-only charts with no fills still miss.
3. **A table-vs-chart discriminator on the candidate region**: regular grid
   spacing + high text density ⇒ table, irregular geometry + sparse text ⇒
   chart. Most robust, most work.

Whatever the choice: **bench before code** (project rule). Extend the labelled
diagram bench (T-035) with LibreOffice-produced pages — charts (bar/line/pie,
from the office-eval corpus) *and* ruled/zebra tables as negatives — and record
precision/recall for the current rules and the candidate fix in the PR.

## Acceptance criteria

- [x] A labelled LO-page bench exists (charts positive, ruled/zebra tables
      negative) alongside the existing diagram bench
      (`scripts/lo_diagram_bench/bench.py`).
- [x] `poi-bar-chart.pptx` (and the corpus's other LO-rendered charts) produce a
      described diagram region end-to-end (7/7 clusterable charts; few-drawing
      chart types documented as known misses in the bench).
- [x] Table pages do not regress: no ruled/zebra table in the corpus is consumed
      as a diagram region (0 false positives; the pre-fix state had 9 — the
      suppression also *frees* those tables for T-031 extraction).
- [x] Bench numbers (before/after) recorded in the PR.
