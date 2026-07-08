# T-079: Charts embedded as raster images are described with the alt-text prompt, losing most of their information

**Status:** Open
**Priority:** Medium — the product's differentiator is figure *interpretation*.
A chart that happens to be a raster image gets ~half the information it could,
purely because of how it was embedded — degraded, not dropped (contrast T-078,
which drops vector bar charts entirely).

## Symptom

figmark picks the description prompt by **detection provenance, not content**
([pipeline.py](../../src/figmark/pipeline.py)): a figure from the vector-drawing
clustering path ([diagrams.py](../../src/figmark/diagrams.py)) gets the rich
4-section `diagrams.prompt`; a figure from `page.get_images()`
([images.py](../../src/figmark/images.py)) gets the generic `description.prompt`
(alt-text). So a **chart embedded as a raster image** is described as if it were
a photo — thin, unstructured, often missing axes/series/numbers. Whole reports
whose charts are raster (e.g. Riksbank Betalningsrapport) never trigger the
chart prompt at all.

## Bench (Riksbank Betalningsrapport 2025, 73 pp, all-raster charts; gemma-4-31B via Berget, 2026-07-08)

Same document and model, only `description.prompt` varied:

| Variant | Decoration skipped | Real charts described (avg words) | Cost |
|---|---|---|---|
| **A — alt-text (current default)** | 7 (under-skips: also spends ~90 words each verbosely describing 9 thematic cover illustrations) | thin, ~87 avg | €0.0096 |
| **B — chart-aware "extract as much as possible"** | 2 (over-describes decoration) | 159 avg (**+78 %**) | €0.0127 |
| **B2 — chart-aware + strict decoration-skip** | **16 (all decoration correctly skipped)** | **177 avg, real charts only** | €0.0119 |

**B2 is a clean win:** genuine raster charts get ~2× the information (structured
title/axes, *every* series enumerated, concrete numbers), decoration is correctly
skipped (no wasted alt-text on cover art), and cost ≈ baseline (skipping
decoration offsets the richer chart output). Verified: the 9 images B2 skips
beyond A are all thematic illustrations (stylised globes, cityscapes,
Sweden-map infographics), **not** data charts — no real chart regressed to skip.
Bonus accuracy: on a 5-line chart, the chart-aware prompt counted all five
series; the alt-text prompt had miscounted four.

Root cause confirmed: the alt-text prompt neither asks for chart structure nor
extracts series/numbers, and the encoding-based routing means raster charts
never see `diagrams.prompt`.

## Impact

- Raster-chart documents (common in government/statistics PDFs that export
  figures as images) lose most of their chart information silently.
- Inconsistent output: the same chart is rich as vector, thin as raster.

## Options

1. **Adaptive `description.prompt` (prompt-only, no code).** Ship the B2 wording:
   decide chart vs photo vs decoration, give charts the 4-section treatment,
   skip decoration with `[SKIP]`. Leanest; big measured win. **Caveat:** relies
   on the model's chart-vs-decoration judgment (worked cleanly here, but the
   boundary is fuzzy — a data-carrying infographic could be skipped on another
   corpus).
2. **Caption-aware routing (code).** If a raster image sits under a
   `Diagram N`/`Figur N` caption in the page text, route it to `diagrams.prompt`;
   else keep alt-text + significance. Uses an existing signal, no extra model
   call, and scopes chart treatment to real figures — more robust than model
   judgment. Preferred hardening.
3. **Two-pass classify-then-route.** A cheap "is this a chart?" call, then route.
   Most explicit, but adds a call per image.

Recommendation: adopt Option 1 as the immediate win (validated on more docs
first), with Option 2 as the robust production routing.

## Acceptance criteria

- Bench on **≥3 raster-chart corpus documents** (not just the Betalningsrapport),
  with before/after avg words on real charts and skip counts recorded in the PR
  (bench-before-code).
- Real raster charts get structured, multi-series descriptions; decoration stays
  `[SKIP]`; **no real chart regresses to skip** (verified, not assumed).
- If prompts go English (see the A/B in the session notes), keep output language
  controlled by `language.output` so Swedish docs still get Swedish descriptions.
- English prompt wording is decided together with T-078's diagram-prompt work so
  the image and diagram prompts stay consistent.
