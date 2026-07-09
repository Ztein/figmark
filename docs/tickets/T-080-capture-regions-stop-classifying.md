# T-080: figmark misses figures because the code tries to guess which regions are charts

**Status:** Open — refactor validated on branch `feat/simpler-extraction-t080`
(commit saved), **blocked on T-081** before merge.
**Priority:** High — figure interpretation is the product's differentiator, and
the coverage bench shows we silently drop ~1 in 4 figures.

## Symptom

The figure-coverage bench (`scripts/coverage_bench`) on real reports:

| Document | Coverage |
|---|---|
| boc-mpr-202410.pdf | 58 % |
| boj-outlook-2410.pdf | 79 % |

Misses are not one chart type: BoC Chart 4 is a plain **line chart**, dropped
because its page has **29 drawings and the gate is 30** (`MIN_DRAWINGS_PER_PAGE`).
Others are bars (`MIN_SOLID_DRAWINGS_PER_CLUSTER`). Relaxing one gate barely helps
— the next arbitrary threshold catches the figure. It is whack-a-mole between
tangled magic numbers.

## Root cause

`diagrams.py` tries to *classify* whether a vector-drawing cluster is a chart
(solid-fill count, page/cluster drawing counts, sloped-member table heuristics).
A real chart fails one of these for reasons unrelated to being a chart. The
premise is wrong: **only a vision model can tell what a region is.**

## Impact

- Silent loss of ~20–40 % of figures on chart-dense PDFs — the highest-value
  content, and exactly what figmark exists to interpret.
- Coverage is unpredictable: the same detector captures a figure in one doc and
  drops an identical one in another, by incidental geometry.

## Options

1. **Capture regions, let the model decide (chosen).** Cluster nearby drawings
   into regions (mechanical), render any region above a size floor, and let the
   vision model + significance gate decide what it is and whether to describe it.
   Removes the chart-classification gates (`MIN_SOLID_*`, page-count) and the
   `solid` machinery. Keeps region-finding + size floor + **table-dedup** (a
   ruled data table already becomes a Markdown table; suppressing it as a picture
   avoids double-representation — a de-dup concern, not classification).
2. Keep tuning the geometric gates. Rejected — the bench shows it is a losing
   game.

## Bench (prototype, 2026-07-08/09, gemma-4-31B via Berget)

Relaxed gates → **BoC 58→100 %, BoJ 79→100 %** caption coverage, plus appendix/
panel charts the metric doesn't even count. Precision high (spot-checked: all
captured regions on BoC are real charts; 1–2 false positives per doc, absorbed
by significance). Cost ~1.4–1.8×. Honest residual: on **LibreOffice-rendered
Office docs** the relaxation over-captures vector decoration — the significance
gate absorbs most, but the fragile `[SKIP]` string lets one junk region leak.
That is why this is blocked on **T-081** (structured describe) before merge.

## Acceptance criteria

- Coverage bench ≥ ~95 % on the sample PDFs (from 58/79 %), recorded in
  `scripts/coverage_bench/BASELINE.md` (before→after).
- No junk in the output: an over-captured non-figure region is cleanly skipped
  (requires T-081). `test_docx_consultation_phantom_images_stay_gone` passes
  honestly (not by raising the bound).
- `diagrams.py` is *simpler* (fewer constants, no `solid`/classification code),
  not merely detuned.
- Cost increase measured and documented.
