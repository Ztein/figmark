# Evaluation report — central-bank corpus, 2026-06-11

figmark v0.2.0+ was evaluated against 31 real economic reports from 9 central
banks and institutions, fetched from the open web. This report covers what was
run, what broke, and a manual quality review of the interpretations.

> **Reproduce:** the corpus and runner live in
> [examples/eval/](../examples/eval/README.md) —
> `python examples/download_eval.py && python examples/run_eval.py`. Write a new
> dated report alongside this one for each future run.

## Corpus

| Institution | Docs | Languages | Notes |
|---|---|---|---|
| BIS | 4 | en | Annual Economic Reports + Quarterly Reviews; heaviest documents |
| ECB | 6 | en | Economic Bulletins + Financial Stability Review |
| Federal Reserve | 5 | en | MPR, FSRs, Beige Books |
| Bank of England | 4 | en | Monetary Policy Reports |
| Bank of Canada | 4 | en | Monetary Policy Reports |
| Bank of Japan | 2 | en | Outlook Reports |
| Czech National Bank | 2 | en | MPR + the chart-dense GEO Chartbook |
| Sveriges Riksbank | 2 | **sv** | Penningpolitiska rapporter |
| Norges Bank | 2 | en | Monetary Policy Reports |

Corpus note: the "German" ECB bulletin (`eb202404.de.pdf`) turned out to serve
English content — the ECB does not translate the full bulletin. figmark's
language detection correctly said English; the corpus annotation was wrong.
(RBA was dropped: rba.gov.au blocks non-browser clients.)

## Aggregate results

- **31/31 documents converted successfully** (after two pipeline fixes below).
- **2 642 pages, 1 498 figures described, 82 skipped as decorative.**
- Total pipeline time ≈ 25 min (two documents concurrently, 8 describe workers
  each); average 48 s/document; largest single document: ECB FSR with 181
  figures.
- Language detection: both Swedish reports → Swedish descriptions in the
  correct formal register; all English reports → English. No mismatches.
- The HTTP service path was smoke-tested separately: the GHCR `:edge` container
  converted a Bank of Canada MPR via `POST /v1/convert` in 28 s with results
  identical in shape to the CLI run (29 pages / 15 figures / 1 skipped /
  English).

## Bugs found by the eval (both fixed, TDD)

The corpus immediately earned its keep — two hard failures on real documents:

1. **T-021 — off-page drawing clusters crashed rendering.** Both BIS Annual
   Reports contain vector drawings with negative y-coordinates (content above
   the page). A filter-passing cluster clamped to a negative-height bbox and
   crashed the PNG writer. Fixed by skipping degenerate post-clip regions;
   regression test added.
2. **T-022 — diagram payloads were sent uncapped.** A 1 MB rendered chart
   region (BIS AR 2024, p. 115) was rejected by the endpoint. Diagrams now go
   through the same resize/re-encode payload cap as raster images; regression
   test added. The very chart that crashed now gets an excellent description
   (verified manually below).

## Manual quality review

**Method.** All 31 outputs were audited at the text level (markdown produced,
document summary present and accurate, description language matches document
language, sampled description per document read for coherence). On top of
that, extracted figures were compared visually against their descriptions for
a sample across institutions and languages.

**Visually verified figures (image vs. description):**

| Figure | Verdict |
|---|---|
| BIS AR 2024 p.115 — 420-word embedding-similarity heatmap | **Excellent**: matrix type, colour scale −1→1, diagonal, zoom-inset, and word examples all correct |
| Riksbanken PPR dec 2025 p.10 — three-panel policy-rate/inflation | **Very good** (Swedish): panels, 4 % peak 2023, 1.75–2 % stabilisation, KPIF series correct; nit: x-axis start misread (2020 vs 2022) |
| Norges Bank MPR 4/25 p.7 — four-panel rate/output gap/CPI/CPI-ATE | **Very good**: all panels and projections correct; nit: CPI-ATE acronym expanded slightly wrong |
| CNB GEO Chartbook p.4 — six-series equity index chart | **Good with a real error**: title/axes/trends correct, but two series colours were swapped (China described with Russia's collapse-and-flatline trajectory) |
| CNB Chartbook skipped image | **Correct skip**: blank decorative background |
| BoJ Outlook skipped images (4 on page 1) | **Correct skip**: the Bank of Japan logotype |

**Decorative-image gate.** 82 images were `[SKIP]`-marked across the corpus;
every sampled case was genuinely decorative (logos, blank backgrounds). No
sampled case of a real chart being skipped.

**Vector-diagram precision.** Of 713 vector-diagram descriptions, 12 (2 %)
were regions that turned out to be logos/decorations (mostly the ECB logo —
the bulletins' charts are raster images, so the logo was the only "vector
diagram" found). These produce honest "this is a logo, not a chart" text —
ugly in the markdown but never fabricated data. Tracked as T-023.

## Weaknesses observed (honest list)

1. **Series-colour attribution in many-series charts.** With 6–7 line series,
   the model can swap colour→label mappings (the CNB equity chart attributed
   Russia's trajectory to China). Structure, axes, and overall trends remain
   correct, but specific series claims in dense charts should be treated with
   care. Mitigation ideas: prompt nudging ("verify each series' colour against
   the legend before attributing"), or accepting it as a model-level limit.
2. **Logo-as-diagram regions (2 %)** — T-023: apply the significance gate to
   diagram regions too, so these are dropped instead of described.
3. **Small quantitative nits** (axis-start years, acronym expansions) occur in
   otherwise-correct descriptions; nothing misleading was found in the sample.

## Conclusion

The pipeline handled a demanding, realistic corpus — 2 600+ pages of
chart-dense central-bank reporting in two languages — with zero failures after
the two fixes, correct language behaviour throughout, a decorative-image gate
that works as designed, and figure interpretations that range from good to
excellent. The single recurring quality risk is series-colour attribution in
charts with many overlapping series.
