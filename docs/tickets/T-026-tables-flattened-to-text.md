# T-026: Tables are flattened to loose text lines — column structure is lost

**Status:** Open
**Priority:** High — data fidelity for the core use case (data-heavy reports)

## Symptom

A table in a PDF comes out of figmark as a run of loose text lines, not a table.
Convert any data-heavy document (e.g. a Riksbank monetary-policy report) and look
at a numeric table in the Markdown: the cells appear as adjacent words/lines in
reading order, columns collapsed, with no `| --- |` Markdown table and no
reliable row/column association.

## Root cause

There is no table detection at all. [`iter_page_blocks`](src/figmark/pdf_loader.py)
builds the page only from `page.get_text("dict")` text blocks (type 0) plus image
blocks, then sorts everything by `(round(y/10), x)`. A table's cells are just text
spans; the 2-D structure is never recovered. The dependency set is PyMuPDF +
Tesseract + Pillow + openai — no pdfplumber, no `find_tables`, no pandas.

## Impact

Anyone converting tabular content loses the data. For monetary-policy reports —
forecast tables, rate paths, inflation figures — the numbers are exactly what a
reader needs, and they come out unparseable. Downstream consumers (search, RAG,
accessibility) cannot recover rows/columns.

## Options

1. **PyMuPDF `page.find_tables()` (TableFinder), render to Markdown.** PyMuPDF is
   already a dependency (`>=1.24`), so this adds **no new package** and keeps the
   image lean and air-gap-friendly. Detect tables per page, emit a GitHub Markdown
   table via a new `TableBlock` placed in reading order, and exclude the consumed
   cells' text from the normal flow so content is not duplicated. Cons:
   TableFinder quality varies on borderless / financial tables.
2. **Add pdfplumber for extraction** (`extract_tables` + table settings), convert
   with a small helper or pandas. Often stronger on ruled tables. Cons: a new
   dependency (+ pandas if used), larger image, overlaps with PyMuPDF.
3. **Hybrid (Intric-style): PyMuPDF detection, pdfplumber as a quality override.**
   Best fidelity, most complexity and the most dependencies.

Recommendation to evaluate: **Option 1 first** — measure detection on the eval
corpus; escalate to pdfplumber (Option 2/3) only if PyMuPDF tables underperform on
the bank's actual table styles. Avoid the Docling/TableFormer stack (heavy PyTorch/
ONNX — contrary to the lean, air-gapped design).

## Acceptance criteria

- [ ] Detected tables render as valid Markdown tables in reading order.
- [ ] Cells consumed by a table are not also emitted as loose text blocks.
- [ ] A `TableBlock` type flows through `output.py` (and annotation, if relevant)
      consistently with text/image/diagram blocks.
- [ ] Tables with empty/merged cells or pure numbers do not crash; a page where
      detection finds nothing falls back to today's text path.
- [ ] If `find_tables` raises on a page, it is logged loudly — not silently
      swallowed (cf. T-024).
- [ ] Validated on the eval corpus, with the count of detected tables reported.
- [ ] No new runtime dependency unless Option 2/3 is chosen and justified here.
