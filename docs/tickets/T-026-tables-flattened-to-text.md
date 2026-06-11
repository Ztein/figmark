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

## What pdfplumber would actually buy us (and why we may not need it)

A reference pipeline (Intric/Docling) runs **both** PyMuPDF and pdfplumber, but
for reasons mostly outside our domain. The two sit on different engines — PyMuPDF
on MuPDF (C, fast), pdfplumber on pdfminer.six (pure Python) — and split the work:

| Capability | Best tool | Do *we* need it? |
|---|---|---|
| Speed, raw text + coordinates | PyMuPDF | yes — already used |
| Render page → image (for OCR) | PyMuPDF | yes — already used |
| Embedded images, vectors, annotations | PyMuPDF | yes — already used |
| Form-field / widget values (checkboxes) | PyMuPDF | no — reports rarely have forms |
| **Table cell/column structure** | **pdfplumber** (ruled & borderless, tunable `table_settings`) | **the one open question** |
| Fine-grained char/line geometry | pdfplumber | no |
| Second parser as a corruption safety net | pdfplumber | nice-to-have, not core |

So of pdfplumber's strengths, **only table extraction is relevant to us.** Intric
also leans on it for form values and as a repair parser; we don't. That collapses
our "add pdfplumber?" decision to a single empirical question: **is PyMuPDF's
`find_tables()` good enough on the bank's actual table styles?** If yes, we stay
single-dependency; if no, pdfplumber is a *targeted* add for tables only, while
PyMuPDF keeps doing everything else.

## Quality evaluation — decide whether PyMuPDF alone suffices

Before writing extraction code, build a small labelled bench and let the numbers
pick between Option 1 and Option 2/3.

1. **Bench set.** ~10–15 representative tables from `eval/`, spanning the styles
   we actually see: ruled grids, borderless number tables, header + footnote,
   multi-line cells, and a wide forecast/rate-path table. Hand-write the
   ground-truth cell grid for each.
2. **Metrics, per table:**
   - **Detection** — was the table region found at all? (binary)
   - **Shape** — are rows × columns correct? (binary)
   - **Cell accuracy** — fraction of ground-truth cells whose text matches exactly
     (precision + recall over cells).
   - **Renders** — does the emitted Markdown parse as a valid table?
3. **Compare** PyMuPDF `find_tables()` vs pdfplumber `extract_tables()` on the
   *same* bench and documents.
4. **Decision rule (write the threshold down).** e.g. "if PyMuPDF reaches ≥ 90 %
   detection and ≥ 95 % cell accuracy across the bench, ship PyMuPDF-only;
   otherwise adopt pdfplumber for tables." Record the actual numbers in the PR so
   the choice is auditable.
5. **Adversarial cases to include** — where PyMuPDF most often loses to pdfplumber:
   borderless tables held together only by alignment, merged/spanned header cells,
   and tables that break across a page boundary.

## Acceptance criteria

- [ ] The labelled bench is built and both engines scored on it; the numbers and
      the PyMuPDF-vs-pdfplumber decision (against the written threshold) are
      recorded in the PR.
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
