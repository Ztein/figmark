# Figure-coverage baseline

**What this measures.** Did figmark capture the figures a document contains? Two
ground-truth modes, chosen automatically:

- **caption** (captioned PDFs): ground truth = the document's own numbered
  captions (`Chart N` / `Figure N` / `Diagram N` / …). A figure number is
  *covered* if figmark produced a non-skipped figure on a page where that caption
  appears. Page-level, so a **lower bound on misses** (a page with two charts
  where one is caught counts both covered; a cross-reference can over-credit) —
  it never cries wolf.
- **image** (documents without captions, e.g. a Word file): ground truth = the
  count of embedded images in the source (icons filtered out). *Covered* =
  distinct images figmark extracted, **deduplicated by content hash** so the
  LibreOffice "same header on every page" phantom repeats collapse to one.

**Scope.** Coverage only — *did we get the figure at all*. It says nothing about
description quality/relevance (that needs an LLM judge; see the session analysis).
Extraction-independent: the same yardstick compares the current geometric
detector against any future extraction approach.

**Run it:**
```bash
python scripts/coverage_bench/coverage.py DOC OUTPUT_DIR [DOC2 OUTDIR2 ...]
```
(`OUTPUT_DIR` = a figmark run dir containing `<name>.figures.json`.)

## Baseline — current `main` extraction (2026-07-09, gemma-4-31B via Berget)

| Document | Mode | Ground truth | Covered | Coverage | Captured |
|---|---|---|---|---|---|
| boc-mpr-202410.pdf (Bank of Canada MPR) | caption | 26 captions | 15 | **58 %** | 16 figs |
| boj-outlook-2410.pdf (Bank of Japan Outlook) | caption | 58 captions | 46 | **79 %** | 55 figs |
| govuk-social-care-consultation.docx | image | 6 images | 6 | **100 %** | 6 unique |
| **Aggregate (caption)** | | **84** | **61** | **73 %** | |
| **Aggregate (image)** | | **6** | **6** | **100 %** | |

**Missed figures (caption present, no captured figure on its page):**
- BoC: Chart 4, 5, 6, 9, 11, 16, 18, 19, 21, 23, 24, 26 (12 of 26)
- BoJ: Chart 1, 4, 5, 6, 7, 13, 14, 17, 18, 19, 52, 56 (12 of 58)

## Reading the two modes

The **caption** docs (chart-heavy central-bank PDFs) are where coverage is the
acute problem: ~1 in 4 charts missed, of mixed type — BoC Chart 4 is a plain
**line chart** dropped by the detector's `MIN_SOLID_DRAWINGS_PER_CLUSTER` gate,
others are bars. This is the number to beat when the geometric pre-classification
is replaced with "render every visual region, let the vision model decide."

The **image** doc (the Word file) shows the opposite: **coverage is already
complete** — figmark finds all 6 embedded images (the LibreOffice→PDF pass
produced 41 placements that dedupe to 6; one repeated header is correctly
skipped). The docx's open questions are *quality* (two logos over-described), not
coverage — so it belongs to the LLM-judge track, but it now has a real coverage
number instead of N/A.
