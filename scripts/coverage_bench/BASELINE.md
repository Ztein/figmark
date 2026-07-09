# Figure-coverage baseline

**What this measures.** Did figmark capture the figures the document itself
declares? Ground truth = the document's own numbered figure captions
(`Chart N` / `Figure N` / `Diagram N` / …). A figure number is *covered* if
figmark produced a non-skipped figure on a page where that caption appears.

**Deliberately a lower bound on the problem.** The match is page-level, so a page
with two captioned charts where figmark caught one counts *both* as covered — and
a cross-reference ("see Chart 5") on another page can over-credit. So true
figure-level coverage is **≤ these numbers**; the metric never cries wolf.

**Scope.** Coverage only — *did we get the figure at all*. It says nothing about
description quality/relevance (that needs an LLM judge; see the session analysis).
Extraction-independent: the same yardstick compares the current geometric
detector against any future extraction approach.

**Run it:**
```bash
python scripts/coverage_bench/coverage.py DOC.pdf OUTPUT_DIR [DOC2.pdf OUTDIR2 ...]
```
(`OUTPUT_DIR` = a figmark run dir containing `<name>.figures.json`.)

## Baseline — current `main` extraction (2026-07-09, gemma-4-31B via Berget)

| Document | Caption word | Captions | Covered | Coverage | Figures captured |
|---|---|---|---|---|---|
| boc-mpr-202410.pdf (Bank of Canada MPR) | Chart | 26 | 15 | **58 %** | 16 |
| boj-outlook-2410.pdf (Bank of Japan Outlook) | Chart | 58 | 46 | **79 %** | 55 |
| **Aggregate** | | **84** | **61** | **73 %** | |

Uncaptioned documents (e.g. `govuk-social-care-consultation.docx`) have no
caption ground truth → **N/A** (measure those with the quality/judge track).

**Missed figures (caption present, no captured figure on its page):**
- BoC: Chart 4, 5, 6, 11, 16, 18, 19, 21, 23, 24, 26 (11 of 26)
- BoJ: Chart 1, 4, 5, 6, 7, 13, 14, 17, 18, 19, 52, 56 (12 of 58)

The misses are not one chart type — BoC Chart 4 is a plain **line chart** dropped
by the detector's `MIN_SOLID_DRAWINGS_PER_CLUSTER` gate, others are bars. This is
the yardstick to beat when the geometric pre-classification is replaced with a
simpler "render every visual region, let the vision model decide" approach.
