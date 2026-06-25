# T-041: Extracted figures aren't machine-addressable for follow-up questions

**Status:** Closed — implemented 2026-06-24. `convert` writes `<stem>.figures.json`
(via `build_figure_manifest` in [output.py](../../src/figmark/output.py)): one entry
per image/diagram with `id, page, kind, bbox, path, description, skipped`; paths are
relative and resolve to the embedded files; skipped figures are flagged, not
dropped. Exposed as `ConversionResult.figures_manifest_path`.
**Priority:** Medium — small, and it unlocks the "ask more about this figure" direction

## Symptom

A conversion already extracts every figure to disk (`out_dir/images/`,
`out_dir/diagrams/`), writes each description to a sibling folder
(`descriptions/`, `diagram_descriptions/`), and the Markdown links each figure
(`![Image, page 3](images/page-003-img-02.png)` + the description as a blockquote).
But there is **no single machine-readable index** tying figure ↔ page ↔ bbox ↔
file ↔ description together. A downstream harness that wants to "ask more about
figure 3 on page 5" has to scrape the Markdown to find the file.

## Root cause

`convert` ([pipeline.py](../../src/figmark/pipeline.py)) writes human-facing
outputs (`<stem>.md`, `raw_text.txt`) and per-figure files, but no structured
manifest — even though it already holds everything needed in `PageData`
(page number, bbox, xref/region index, path, description, skip flag).

## Impact

The output is a human document, not a queryable contract. The stated product
direction — keep the Markdown as the representation, but let a later step ask
follow-up questions about a specific extracted figure — needs a stable, addressable
index, not Markdown scraping.

## Options

1. **Emit `figures.json` next to `<stem>.md`** — a list of
   `{id, page, bbox, kind: image|diagram, path (relative), description, skipped}`
   with stable IDs (e.g. `page-003-img-02`). Built directly from `PageData`.
2. Embed structured front-matter / data attributes inside the Markdown itself.
3. Both — Markdown for humans, manifest for machines.

Recommendation: **Option 1** — a separate manifest keeps the Markdown clean and
gives consumers a single file to read.

## Acceptance criteria

- [ ] A figures manifest is written alongside the Markdown for every conversion.
- [ ] Every embedded/described figure appears with id, page, bbox, kind, relative
      path, and description; significance-skipped figures are flagged, not dropped.
- [ ] Each manifest path resolves to a real file (round-trip checked).
- [ ] `ConversionResult` exposes the manifest path; offline test covers it.
