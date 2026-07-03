# T-065: Office support depends entirely on a LibreOffice PDF render — no way to interpret OOXML directly

**Status:** Open
**Priority:** Medium — the whole Office tranche (T-054) rides one heavyweight
step; several downstream limitations (T-056 page explosion, borderless flatten,
dropped comments/notes, the ~1 GB image variant) are consequences of *how* we
ingest Office, not of the formats themselves.

## Symptom

Every docx/xlsx/pptx is ingested by **rendering it to PDF with LibreOffice
headless** (`office.py`, T-054) and then running the PDF pipeline. There is no
path that reads the OOXML directly. Consequences observed in the office-eval
corpus:

- **Pagination artefacts.** A spreadsheet has no intrinsic pages; LibreOffice
  paginates it into print pages, so a long sheet explodes into hundreds of
  pages of loose, flattened numbers (`riksbank-monthly-fx.xlsx` → 380 pages,
  T-056) and borderless tables lose their column↔value structure (T-050/T-056).
  The *sheet itself* is a clean grid (openpyxl reads `riksbank`'s data as one
  9099×7 table) — the mess is introduced by the render, not present in the file.
- **Content the render drops.** LibreOffice `--convert-to pdf` discards
  speaker notes and comments (annotation layers), renders SmartArt as shapes
  without text, and does not render charts embedded in xlsx — all noted as
  known limits in T-054. These live in the OOXML and are reachable without a
  render.
- **Dependency weight.** The render needs a ~1 GB LibreOffice install, shipped
  as a separate image variant precisely to keep its CVE surface off the default
  image (T-054). A native reader would be a light, pure-Python dependency.
- **CLI gap (related, found 2026-07-03).** The `figmark` CLI does not run the
  Office→PDF step at all (only the HTTP surfaces do), so `figmark deck.pptx`
  opens the file in PyMuPDF and silently emits a degraded, near-empty result.
  That specific fail-loud violation is arguably its own ticket, but it is a
  second symptom of Office ingestion being bolted onto a PDF-only core.

## Root cause

figmark's pipeline consumes a PyMuPDF `Document`, so *everything* must become a
page-based render first. Office formats are page-less, structured XML in a zip
(OOXML): paragraphs/tables/runs (docx), cells/sheets (xlsx), slides/shapes
(pptx), with embedded media as zip parts and charts as chart XML. Flattening
that to a print render is lossy and heavy — it is the only adapter that exists,
not the only one possible.

## Why this is not just "use a lightweight extractor" (the T-054 tension)

T-054 **deliberately rejected** lightweight text extractors (`python-docx` /
`openpyxl` / `python-pptx`, MarkItDown, pandoc) as the *primary* path, because
they extract text/structure but **drop embedded figures and charts** — and
figure interpretation is figmark's whole differentiator (see the product
vision). Any native path must clear that same bar: it has to surface the
figures/charts for the vision model, not silently lose them. That is the hard
part and the reason this is a real project, not a swap.

The opening exists because OOXML *does* carry the figures: raster images are
zip parts (`word/media/*`, `ppt/media/*`), and charts are structured
`chartN.xml` definitions (series + values). So a native reader can extract the
raster media directly and either (a) reconstruct a chart image / a data table
from the chart XML, or (b) render just the chart, without rendering the whole
document. Preserving the differentiator is achievable — it is just work.

## Impact

- **Fidelity.** Data sheets keep their structure (one table per sheet, no
  page explosion); notes/comments/SmartArt text survive; xlsx charts become
  describable.
- **Leanness.** The default image could accept Office with a light pure-Python
  dependency instead of a 1 GB variant — the air-gapped-image constraint is
  easier to hold.
- **Cost/latency.** No per-document `soffice` subprocess (a 2–4 s conversion
  today) and no describing figures duplicated across LibreOffice's per-page
  image resources (the phantom-figure problem T-054 had to special-case).

## Options

Not mutually exclusive; a format-by-format mix is likely.

1. **Native structural readers per format, render only the figures.** Read
   docx/xlsx/pptx structure with `python-docx` / `openpyxl` / `python-pptx`
   into figmark's block model (headings, paragraphs, tables, text), pull raster
   media straight from the zip, and render charts from their XML (or extract the
   embedded chart image where one is cached). Highest fidelity and leanest
   runtime; the most work, and needs a bench proving figures are *not* lost
   vs the LibreOffice path.
2. **Hybrid: native for structure, keep LibreOffice only for figures.** Use the
   native reader for text/tables/notes and fall back to a *targeted* render
   (a single slide, a single chart) only for visual elements the reader can't
   reconstruct. Removes the pagination/flatten problems while accepting the
   dependency until (1) closes the figure gap. A stepping stone.
3. **xlsx-first (dovetails with T-056).** Spreadsheets are the worst fit for
   the render and the easiest native win (cells are already a grid). Ship the
   openpyxl sheet→table path decided in T-056 as the first native reader, learn
   from it, then generalise to docx/pptx.
4. **Do nothing / status quo.** Keep the LibreOffice-only path and its
   documented limits. Cheapest; leaves T-056's flatten and the notes/comments
   loss unaddressed and the default image render-bound.

## Acceptance criteria

- [ ] A recorded decision on the native path, per format, with a **fidelity
      bench** (figures/charts preserved? tables? reading order? notes/comments?)
      comparing native vs the current LibreOffice render on the office-eval
      corpus — the bench-before-code rule, and the exact bar T-054 set.
- [ ] At least one format reads natively end-to-end **without** a full-document
      PDF render, with its embedded figures still extracted and described (the
      differentiator is preserved, not dropped).
- [ ] Any new dependency is justified in this ticket and, if it stays
      pure-Python, evaluated for inclusion in the **default** image (not only
      the Office variant).
- [ ] The page-explosion / borderless-flatten failure modes (T-056/T-050) are
      measured on the native path and shown fixed or documented.
- [ ] Formats still handled only via the render (if any) are stated loudly, so
      no silent fidelity cliff between "native" and "rendered" Office inputs.
