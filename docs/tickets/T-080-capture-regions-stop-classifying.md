# T-080: figmark misses figures because the code tries to guess which regions are charts

**Status:** Closed — one-box-per-page shipped (with T-081's structured skip in
place). Resolution below.
**Priority:** High — figure interpretation is the product's differentiator, and
the coverage bench showed we silently dropped ~1 in 4 figures.

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

## Resolution (2026-07-22)

Shipped as **one box per page-band** (Option 3), with the open split question
resolved by bench:

- **Banding:** a page's filtered drawings group into maximal vertically
  overlapping runs; adjacent bands merge unless a **body paragraph** sits in
  the gap. Captions/source lines between two charts do not split — they belong
  to the figure and land inside the rendered box.
- **Paragraph vs furniture** (the open question): word counts alone do NOT
  separate them — BIS panel-title rows run 15–44 words. Bench-validated rule:
  ≥ 20 words AND ≥ 2 lines AND sentence punctuation (`.`/`,` — tick-label runs
  like "RO CL MX …" never have it; junk leakage 107→0 words on BIS).
- **Paragraph guard (new, found by the bench):** a one-box band can
  legitimately cover flowing text (column layouts, bridged bands) — measured
  29/156/538 swallowed paragraph-words on BoC/BoJ/BIS even with per-band
  boxes. `text_block_in_region` therefore never claims a body paragraph: mild
  duplication beats silent deletion. Rescued prose: 831/2016/9350 words on
  BoC/BoJ/BIS, junk 0.
- **Page furniture:** a drawing spanning ≥ 90 % of a page dimension (margin
  rules, borders) is filtered — one 5 px margin bar otherwise bridged every
  band on a table page into a full-page box.
- **Tables:** drawings the table path owns are excluded *before* banding. A
  ruled table `find_tables` misses (the report's p70) is now captured for the
  model instead of dropped — it addresses the T-050 symptom instead of
  flattening to loose text.

**Geometric caption coverage** (extraction-side, `scripts/coverage_bench`
ground truth): BoC **58→100 %**, BoJ **79→100 %**, BIS/Fed/Riksbank PPR/
Riksbank FSR **100 %** — nothing missed on six docs. Region counts bounded:
35/54/81/64/44/28 — aggregate **301→284 vs main over seven docs** (BIS halves
as panels merge; BoC/Fed roughly double, exactly where main dropped figures).
T-078's three dropped FSR bar/combo charts (p27/37/41) all capture.

Live before→after numbers recorded in `scripts/coverage_bench/BASELINE.md`.
