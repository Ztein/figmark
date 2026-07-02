# T-055: Vector charts in LibreOffice-produced PDFs are missed by diagram detection

**Status:** Open
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

- [ ] A labelled LO-page bench exists (charts positive, ruled/zebra tables
      negative) alongside the existing diagram bench.
- [ ] `poi-bar-chart.pptx` (and the corpus's other LO-rendered charts) produce a
      described diagram region end-to-end.
- [ ] Table pages do not regress: no ruled/zebra table in the corpus is consumed
      as a diagram region (T-031 still owns them).
- [ ] Bench numbers (before/after) recorded in the PR.
