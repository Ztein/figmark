# T-001: Vector charts missed entirely

**Status:** Closed — fixed 2026-05-20 via approach F (PyMuPDF drawing clustering)
**Priority:** HIGH — core functionality broken for documents with charts
**Discovered:** 2026-05-20 during a manual run against `penningpolitisk-rapport-mars-2026.pdf`

## Resolution

Implemented in [src/figmark/diagrams.py](../../src/figmark/diagrams.py). The pipeline now
detects chart regions via a four-step algorithm:
1. Filter drawings (size + page background)
2. Union-find clustering on spatial proximity (MERGE_DISTANCE=3)
3. Y-gap split: divide clusters with internal gaps > 40 px (separates stacked charts)
4. Text expansion: grow the bbox to capture axis titles and source lines, bounded
   by other clusters so they don't merge together

Configurable via the `diagrams:` section in [config.example.yaml](../../config.example.yaml).

Live test: [tests/test_pipeline.py::test_pipeline_diagrams_extracted_from_penningpolitisk](../../tests/test_pipeline.py)
verifies that 4 charts are extracted from pages 11 + 68 of the monetary policy report,
with descriptions that mention axes, forecasts and series.

## Symptom

Running against the Riksbank's monetary policy report (72 pages, packed with charts) produced **3 descriptions** — all of cover graphics and back-page panels. Zero charts were described even though the report's content essentially IS charts.

```
Describing 3 image(s) via google/gemma-4-31B-it …
  page 1: page-001-img-01.jpeg → API
  page 1: page-001-img-02.jpeg → API
  page 72: page-072-img-01.png → API
```

## Root cause

[src/figmark/images.py](../../src/figmark/images.py) uses `page.get_images(full=True)` + `doc.extract_image(xref)`. That API only returns **embedded raster images** (JPEG/PNG bytes stored as XObjects in the PDF).

The Riksbank's charts are **vector graphics** (PDF path/draw commands) — likely exported from matplotlib/R/d3 to PDF, where every curve, axis and label becomes individual path instructions. Inspection confirms this:

```
Total raster images:     10  (7 of which are <50x50 decorative icons)
Total vector drawings:   4583
Pages with drawings:     65 / 72
```

Top 10 pages by drawing count:
```
Page 71: 236   Page 69: 211   Page 68: 206   Page 70: 190
Page 11: 174   Page 66: 174   Page 10: 165   Page 45: 156
Page 35: 145   Page 14: 128
```

All of these pages contain charts.

## Impact

The pipeline is effectively unusable for any document with charts — which is most government reports, economic reports, scientific papers with figures (beyond embedded photographs), research overviews, etc. That's exactly the wrong place to fail in an accessibility pipeline: the main case we want to support is precisely reports with visual data presentation that need to be described.

## Options

### Option 1: Render clustered drawing regions as images
Use `page.get_drawings()`, group overlapping/nearby bounding boxes into clusters, render each cluster region via `page.get_pixmap(clip=bbox)`, send to Gemma.

- ✅ Preserves position information (we know where the chart sits → correct cropping)
- ✅ Distinguishes multiple charts on the same page
- ❌ A clustering algorithm has to be implemented and tuned
- ❌ Drawings for table lines and text decoration become false positives

### Option 2: Heuristic full-page rendering at high drawing density
If a page has many drawings (threshold: e.g. > 50), render **the whole page** as an image and send it to Gemma with the prompt "describe all charts, graphs and maps on this page". Low-density pages (table borders etc.) are skipped.

- ✅ Simple to implement
- ✅ Robust against false positives (no cluster detection needed)
- ❌ One page = one description. If the page has 4 separate charts they get blended into one text
- ❌ Loses per-chart position information
- ❌ More expensive: one API call per chart page (estimate for the Riksbank report: ~30 calls)

### Option 3: Hybrid — Option 2 as default, opt-in Option 1 later
Start with Option 2 (fast to deliver value). Migrate to Option 1 if/when we need per-chart precision.

- ✅ Ships the feature today
- ✅ Limited technical debt if we later want precision
- ❌ Temporarily lower precision quality

### Option 4: Combine raster + drawing detection
Keep the current raster extraction. Add drawing rendering. On pages with BOTH embedded raster images AND drawings: render both, avoiding duplicates with a bbox-overlap check.

- ✅ Handles mixed documents naturally
- ❌ Complexity grows
- ❌ The bbox-overlap check is fiddly

## Recommendation

**Option 3 (Hybrid)**, starting with Option 2. Rationale: the pipeline needs to work for charts NOW. Per-chart precision is nice, but "describe the whole page" as one text block is still considerably better than nothing for accessibility purposes. The migration to Option 1 can be done incrementally later.

## Acceptance criteria

- [ ] `penningpolitisk-rapport-mars-2026.pdf` produces at least 20 descriptions (rough proxy for "we capture charts")
- [ ] The `<name>.md` output contains `[Image: …]` blocks that refer to chart content, not just the cover
- [ ] The threshold for "page counts as a chart page" is configurable in `config.yaml`
- [ ] The Pentland PDF (text article without charts) still produces ~2 descriptions (regression guard)
- [ ] A live test that verifies at least one chart description has been run

## Suggested config fields
```yaml
diagrams:
  # When a page has at least this many drawing operations it is treated as a chart page
  drawings_threshold: 50
  # DPI and quality for rendering chart pages (sent to Gemma)
  render_dpi: 200
  jpeg_quality: 85
  # Separate prompt for charts (otherwise description.prompt is used)
  prompt: |
    Describe the charts, graphs and maps on this PDF page for
    users who need descriptive text. Describe what each chart shows,
    which axes and units are used, and the most important trends or
    observations. If the page has several charts, describe each one
    separately.
```
