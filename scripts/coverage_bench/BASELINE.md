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

## After T-080 — one-box-per-page extraction (2026-07-22, gemma-4-31B via Berget)

Same yardstick, same documents, live end-to-end runs with the T-080 band
extraction + T-081 structured skip:

| Document | Mode | Ground truth | Covered | Coverage | Captured | Skipped by model |
|---|---|---|---|---|---|---|
| boc-mpr-202410.pdf | caption | 26 captions | 26 | **100 %** (was 58 %) | 32 figs | 3 (cover/decoration) |
| boj-outlook-2410.pdf | caption | 58 captions | 58 | **100 %** (was 79 %) | 55 figs | 4 |
| riksbank-fsr-202505.pdf | caption | 28 captions | 28 | **100 %** (3 charts dropped before, T-078) | 38 figs | — |
| **Aggregate (caption)** | | **112** | **112** | **100 %** | | |

**Missed figures: none.**

**Cost** (per full conversion, live): BoC 37 calls / 46.8k tokens ≈ 0.016 EUR,
BoJ 61 calls / 86.1k tokens ≈ 0.030 EUR, FSR 40 calls / 56.7k ≈ 0.019 EUR. Aggregate regions across seven corpus
docs are 301→284 vs main (BIS AR halves as multi-panel figures merge into one
box; BoC/Fed roughly double — exactly where main dropped 1 in 4 figures), so
capture-100 % costs about the same as the old gated detector overall.

**Skip behaviour (T-081):** over-captured non-figures (cover decorations,
title-page rules) return `is_figure=false` and are cleanly skipped — 3/35 on
BoC, 4/59 on BoJ, no junk in the Markdown.

Geometric (extraction-side) coverage is also 100 % on bis-ar-2024,
fed-mpr-202407 and riksbank-ppr-202503. The three FSR bar/combo charts T-078
reported dropped (pages 27/37/41) are captured *and described correctly* in
the live FSR run — T-078 closes with this baseline.
