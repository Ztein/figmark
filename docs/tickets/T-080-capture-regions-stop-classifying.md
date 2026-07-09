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

1. **Capture per-cluster regions, let the model decide.** Cluster nearby drawings
   into regions (mechanical), render any region above a size floor, let the model
   decide. Removes the chart-classification gates. **Problem found (2026-07-09):**
   on big/layout-heavy reports this *explodes* — BIS Annual Report captured **105
   regions** (each = an API call), and multi-panel figures split into isolated
   panels that lose their shared title/story. Also re-accumulates heuristics
   (density floors, figure-band caption parsing) — back toward the mess we removed.
2. Keep tuning the geometric gates. Rejected — whack-a-mole between magic numbers.
3. **One box per page (chosen direction).** The whole rule: on each page, union
   the visual content into one box; split into two only when the content is
   clearly separate. No clustering thresholds, no caption parsing, no
   chart-vs-not classification — the model gets the whole visual block and does
   all the interpreting. Verified: BIS 105→**51** regions (bounded to ~1–2/page,
   no explosion); Graph 6's three panels land in one box (context preserved); and
   a downscaled union image read fine axis labels as well as a full-res panel
   (resolution loss not a practical problem — T-083). The figure *title* need not
   be inside the box: it's carried by the surrounding-text context figmark
   already sends.

**Open question (investigation, resolve in the quality review):** is one box per
page always fine, or should we split when two visuals *don't* belong together?
The reasonable, non-arbitrary signal is **body text between two visual groups**
(a real paragraph → separate figures; only whitespace/labels between → same
figure) — mechanical, uses the reading-order text figmark already has, and is
understandable. A bare whitespace-gap threshold is a cruder proxy.

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
