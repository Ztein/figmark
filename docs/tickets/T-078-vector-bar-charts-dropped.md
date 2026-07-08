# T-078: Vector bar and combo charts are silently dropped by the diagram detector (line charts only)

**Status:** Open
**Priority:** High — figure interpretation is figmark's differentiator, and this
silently loses a whole class of charts. A dropped bar chart leaves only its
caption text; the data is gone, with no warning — the exact "silent degradation"
the project bans.

## Symptom

On chart-dense born-digital PDFs whose charts are **vector** drawings, the
vector-diagram detector reliably finds **line** charts but misses **bar charts**
and **bar+line combos** entirely. The missed chart is not rendered, not
described, and not flagged — only its caption/`Källa:` line survives in the body
text.

## Bench (two real runs, 2026-07-08, gemma-4-31B-it via Berget)

**Riksbank FSR 2025:1** (`riksbank-fsr-202505`, 53 pp, vector charts) — 24 diagram
regions detected + described. Interpretation quality high (verified against
source: axis ranges, line levels, trends, series ordering all correct, incl. a
standardized negative-valued axis). But three bar/combo charts were **dropped**:

| Chart | Page | Type | Outcome |
|---|---|---|---|
| Diagram 10 — Svensk varuexport | 27 | stacked bar | dropped (caption-only) |
| Diagram 20 — Likviditetskvoter | 37 | grouped bar | dropped |
| Diagram 24 — Nettofondflöden | 41 | bar + line, dual axis | dropped (has a line, still missed) |

**Riksbank Betalningsrapport 2025** (`riksbank-betalningsrapport-202503`, 73 pp) —
**0** vector diagrams detected, because this report embeds its charts as **raster
images**. Those went through the image path instead: 31 images described (24 kept
after the significance gate), **including bar charts described richly** — e.g.
page 16 read the title, x-axis categories, both series (Kort/Swish) and the
average-marker diamonds, with correct observations.

**The controlled contrast:** the *same chart class* (bar) is **dropped** when it
is vector (FSR) but **described well** when it is raster (Betalningsrapport). So
the description model handles bar charts fine — the defect is isolated to the
**vector-diagram detection/clustering**, which keys on line-like geometry and
does not recognise bar-rectangle clusters as a chart region.

## Root cause (hypothesis — confirm with a bench)

`diagrams.py` clusters vector drawings into candidate chart regions. The
clustering/scoring appears tuned to stroked poly-lines; filled-rectangle bar
geometry either fails the cluster threshold or is scored below the significance
gate, so a bar chart yields no region. A combo chart (Diagram 24) is missed too,
suggesting the bars suppress or fragment the line cluster rather than the line
rescuing it.

## Impact

- Silent loss of bar/combo charts on vector-PDF reports — the highest-value
  content in many central-bank/statistics documents (payment shares, export
  splits, liquidity ratios are almost always bars).
- Inconsistent behaviour: identical charts are captured as raster but dropped as
  vector, so quality depends on how the publisher happened to embed the figure.

## Options

1. **Extend vector detection to bar geometry.** Teach `diagrams.py` to recognise
   clusters of aligned filled rectangles (axis-anchored, regular spacing) as a
   chart region. Most direct fix; needs a labelled bar-chart bench (T-030/T-035
   template) and a tuned threshold so axis ticks/tables aren't false-positived.
2. **Rasterise-and-detect fallback.** For pages with drawings that fail line
   clustering, render the page region and reuse the image path (which already
   describes bars well). Cheaper to build; costs a render per candidate page.
3. **Loud gap report.** At minimum, when a `Diagram N` caption is found on a page
   with vector drawings but no detected region, warn/log the suspected miss
   (fail-loud) so it is never silent — pair with option 1 or 2.

## Acceptance criteria

- A labelled bench of vector bar/combo charts (start from the FSR's Diagram 10/
  20/24) with a written recall threshold and before/after numbers in the PR
  (bench-before-code).
- The three FSR bar/combo charts are detected and described (or a recorded,
  justified decision), verified live.
- No new false positives on the existing eval corpus (line charts, tables, axes
  not mis-detected as bar regions) — measured, not assumed.
- A dropped chart is never silent: at minimum a loud warning when a captioned
  chart has no captured region.
