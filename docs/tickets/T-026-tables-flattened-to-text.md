# T-026: Tables are flattened to loose text lines — column structure is lost

**Status:** Open (un-parked 2026-06-24) — the resume condition is met: the eval
corpus now contains documents with real ruled data tables. Execution is split into
[T-030](T-030-labelled-table-bench.md) (build the labelled bench) and
[T-031](T-031-conservative-table-extraction.md) (filtered extraction + `TableBlock`).
See the 2026-06-24 update below.
**Priority:** High — data fidelity for the core use case (data-heavy reports)

## Update 2026-06-24 — un-parking: the corpus now has real tables

When this was parked (2026-06-11) the only eval document was the chart-heavy
`penningpolitisk-rapport-mars-2026.pdf`, which has **no** ruled data tables. The
eval corpus has since grown to ~32 central-bank PDFs, so the "validate on a
table-heavy document first" resume path is now possible. Ran an unlabelled
detector probe ([scripts/probe_tables.py](../../scripts/probe_tables.py)):
PyMuPDF `find_tables()` per page, scoring each hit by rows×cols, non-empty-cell
ratio, and overlap with a detected diagram region.

**Documents with real ruled data tables (the validation set):**

| Document | Pages w/ real tables | What they are |
|---|---|---|
| `norges-mpr-4-2025` / `norges-mpr-2-2025` | 17,18,27,53,54,55 / 19,32,63,64,65 | Forecast tables, year columns + revision deltas `1.9 (0.1)`; **same structure across editions** |
| `boc-mpr-202401` / `boc-mpr-202407` | 6,14 / 6,14,15 | GDP-contribution tables, clean numeric grids |
| `fed-mpr-202407` | 53 | Fed balance-sheet table |

**Critical caveat — raw counts lie.** Two documents reported high `find_tables`
counts that are *false positives* on inspection, so detection count alone is not a
quality signal:
- `ecb-fsr-202411` → 70 "tables" that are actually **chart-caption rows** laid out
  in columns (`a) Inflation… b) 2025 real GDP… c) Average potential…`), not data.
- `bis-ar-2024` → 10 "good" + 126 empty; the non-empty ones are mostly **chart
  axis-tick ladders** (`5 / 4 / 3 / 2 / 1 / 0`), not data.

The Riksbank reports (`riksbank-ppr-202503`, `-202512`) and `penningpolitisk-
rapport` return **0 tables** — their data lives in vector charts, already handled
by the figure pipeline. This confirms the original parking rationale: naive
extraction injects convincing garbage, and the original corpus genuinely had
nothing to detect.

**Refined filter (sharpens resume-path Option 1, still no new dependency).** The
naive non-empty-ratio + min-size filter is not enough — it lets chart captions and
axis ladders through. Three additional gates, all derivable from data we already
have:
1. **Drop diagram overlaps.** Reject a table whose bbox overlaps a detected
   diagram region (`find_diagram_regions`, already in [diagrams.py](src/figmark/diagrams.py))
   by >50%. This zeroes the BoE-MPR false positives (all hits sat on charts).
2. **Require a numeric body.** Demand ≥3 rows AND a meaningful fraction of cells
   that parse as numbers / parenthesised deltas → kills `ecb-fsr`'s 1–2-row prose
   caption rows.
3. **Reject single-column number ladders.** A lone numeric column with empty
   neighbours is a chart axis → kills `bis-ar`'s tick scales.

With these gates the behaviour is correct: real tables (Norges/BoC/Fed) emit as
Markdown; chart-heavy docs (Riksbank/BoE/BIS) fall back silently to today's text
path — no garbage injected. The numbers and the PyMuPDF-vs-pdfplumber decision get
recorded in [T-030](T-030-labelled-table-bench.md).

**Outcome ([T-030](T-030-labelled-table-bench.md), 2026-06-24):** the labelled
bench scored PyMuPDF + filter at **100 % detection, 99 % cell-recall, zero
false-positive leaks** on the controls; pdfplumber managed only 80 % recall and
flooded 203 false tables on `bis-ar` without a filter. **Decision: ship
PyMuPDF-only + the 3-gate filter, no new dependency.** Productionisation is
[T-031](T-031-conservative-table-extraction.md).

## Bench results (2026-06-11) — why this is parked

Ran the planned quality bench on the real corpus
(`eval/penningpolitisk-rapport-mars-2026.pdf`, 72 pages):

| Engine / strategy | Result |
|---|---|
| PyMuPDF `lines` / `lines_strict` | 0–1 tables — degenerate, empty |
| PyMuPDF `text` | 69 "tables" — **false positives**: ordinary prose chopped into cells |
| pdfplumber `lines` (default) | 20 "tables" on 11 pages — but the cells are **empty**: it latches onto **chart gridlines/axes** |
| pdfplumber `text` | 71 "tables" — same prose-as-table garbage |

**No engine/strategy extracts reliable data tables from this report.** The reason
is structural: this corpus is **chart-heavy** — its quantitative data lives in
graphs (already described by the vision pipeline as figures), not in ruled text
tables. "lines" detectors catch chart gridlines → empty tables; "text" detectors
turn prose → tables. Shipping the naive approach would **inject garbage tables**
into otherwise-clean output, which is worse than the status quo.

This is exactly what the bench-before-code step was meant to catch.

## Decision / path to resume

Do **not** ship the simple "find_tables → Markdown" approach. Two ways forward
when this is picked up again:

1. **Conservative pdfplumber + quality filters.** Extract only tables that pass:
   non-empty-cell ratio above a threshold, **not overlapping a detected diagram
   region** (we already find those — drops chart-gridline false positives), and a
   minimum rows/cols. Adds the pdfplumber dependency. Yields real tables where
   they exist and stays silent on chart-heavy docs.
2. **Validate on a table-heavy document first.** Add a Riksbank doc that actually
   has ruled data tables (e.g. a statistical appendix) to `eval/`, re-run the
   bench, and tune filters against real positives before shipping.

(The original symptom, options, and the labelled-bench design below remain valid
for whoever resumes this.)

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
