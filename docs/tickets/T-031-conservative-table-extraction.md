# T-031: Conservative table extraction → Markdown via a TableBlock

**Status:** Closed — implemented 2026-06-24. New `tables.py` ports the validated
3-gate filter; `TableBlock` flows through `pdf_loader` → `pipeline` → `output.py`
as a GitHub Markdown table; text spans consumed by a kept table are dropped from
the loose flow; `find_tables` errors are logged loudly, never swallowed. Gated by
`tables.enabled` in config. Annotation: tables are **not** embedded as PDF text
annotations (they are text content carried by the Markdown, not visual alt-text).
No new runtime dependency (PyMuPDF only, per [T-030](T-030-labelled-table-bench.md)).
**Priority:** High — the data-fidelity payoff of [T-026](T-026-tables-flattened-to-text.md)
**Parent:** [T-026](T-026-tables-flattened-to-text.md)

## What to build

Productionise the validated approach from the bench (T-030): PyMuPDF
`find_tables()` + the refined 3-gate filter, **no new runtime dependency**
(pdfplumber was evaluated and rejected — see T-030). The filter prototype lives in
[scripts/table_bench/bench.py](../../scripts/table_bench/bench.py) (`keep_table`,
`_col_roles`); port it into the package rather than rewriting it.

The detection + filter, in order (gates from the T-026 2026-06-24 update):
1. Run `page.find_tables()` per page.
2. **Drop diagram overlaps** — reject any table whose bbox overlaps a detected
   diagram region (`find_diagram_regions` in [diagrams.py](src/figmark/diagrams.py))
   by >50 %.
3. **Require a numeric body** — keep only tables with ≥3 rows and a meaningful
   fraction of cells parsing as numbers / parenthesised deltas (drops chart-caption
   rows).
4. **Reject single-column number ladders** — a lone numeric column with empty
   neighbours is a chart axis (drops axis-tick scales).
5. Survivors also clear the basic gate: non-empty-cell ratio ≥ 0.6, ≥ 2 columns.

## Plumbing

- Add a `TableBlock` dataclass to [pdf_loader.py](src/figmark/pdf_loader.py)
  alongside `TextBlock` / `ImageBlock` / `DiagramBlock`, carrying the cell grid and
  bbox, placed in reading order by the existing `(round(y/10), x)` sort.
- **Exclude consumed cells from the text flow** — text spans inside a kept table's
  bbox must not also be emitted as loose `TextBlock`s (no duplication). cf. how
  diagram regions already suppress their internal text.
- Flow `TableBlock` through [output.py](src/figmark/output.py) consistently with
  the other block kinds, rendering a GitHub Markdown table. Decide and note whether
  it also flows through [annotate.py](src/figmark/annotate.py).
- **Loud on failure (cf. [T-024](T-024-audit-silent-fallbacks-and-hidden-defaults.md)):**
  if `find_tables` raises on a page, log it loudly — do not silently swallow. A
  page where detection finds nothing falls back to today's text path.

## Acceptance criteria

- [ ] Detected tables render as valid Markdown tables in reading order.
- [ ] Cells consumed by a kept table are not also emitted as loose text blocks.
- [ ] `TableBlock` flows through `output.py` (and annotation if relevant)
      consistently with the text/image/diagram blocks.
- [ ] Tables with empty/merged cells or pure numbers do not crash; a no-detection
      page falls back to the text path.
- [ ] `find_tables` raising on a page is logged loudly, not swallowed.
- [ ] Validated on the eval corpus: real tables emit (Norges/BoC/Fed), chart-heavy
      docs stay silent (Riksbank/BoE/BIS); the detected-table count is reported.
- [ ] No new runtime dependency unless T-030's numbers chose pdfplumber, justified here.
