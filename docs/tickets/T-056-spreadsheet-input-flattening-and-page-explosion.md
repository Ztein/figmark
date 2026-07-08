# T-056: Spreadsheet input — borderless sheets flatten to label/value soup and big sheets explode into hundreds of pages

**Status:** Closed — **guardrail shipped + extraction path decided (2026-07-03).**
The page-explosion half is fixed loudly: `office.py` counts the produced PDF's
pages and, for a spreadsheet source over `SPREADSHEET_PAGE_WARN_THRESHOLD`
(50) pages, logs a **loud warning** naming the file and the flatten cause —
never a silent 380-page wall (criterion 3). The flatten half (borderless →
label/value soup) is **decided but deferred to a scoped follow-up**: the bench
below shows openpyxl (Option 1) is the right extractor, but wiring a
spreadsheet-native table path that *coexists* with the LO-PDF chart path is a
real architectural change with its own fidelity bench and a new (Office-variant)
dependency — it must not be rushed in as a batch tail. Recorded here so the
next PR starts from the numbers, not a blank page.
**Priority:** Medium — the page-explosion guardrail shipped; the borderless-flatten
extraction path is a scoped follow-up.

## Bench (2026-07-03) — LO-PDF pagination vs openpyxl direct read

Measured across the office-eval xlsx corpus (`--convert-to pdf` page count vs
`openpyxl` used-range dims):

| File | LO-PDF pages | openpyxl (largest sheet) |
|---|---|---|
| `riksbank-monthly-fx.xlsx` | **380** | one `Data` sheet, 9099×7 |
| `poi-formula-eval.xlsx` | 79 | `EverythingTests` 1504×38 |
| `socialstyrelsen-covid.xlsx` | 53 | 12 sheets, ≤160 rows each |
| `poi-many-merges.xlsx` | 1 | `Sheet1` 50000×3 |
| `ons-accessible-tables.xlsx` | 21 | 7 sheets, clean grids |
| `scb-amneslarare.xlsx` | 10 | 3 sheets, ruled — already OK |

openpyxl reads each sheet as **one structured grid** (a 380-page FX series is a
single 9099×7 table); LO-PDF's page count is a print-pagination artefact, not
content. So Option 1 is the correct data-fidelity path — pending the coexistence
+ dependency work.

## Symptom

Two related observations from the office-eval corpus run through the
LibreOffice → pipeline path (2026-07-02):

1. **Borderless sheets flatten.** `ons-accessible-tables.xlsx` (accessibility-
   styled, no ruled borders) yields zero Markdown tables — every row becomes
   alternating label/value text lines. Column↔value attribution survives only
   for trivially narrow sheets. This is T-050's exact symptom, but for
   spreadsheets it is the *primary* content, not an edge case.
2. **Big sheets explode.** `riksbank-monthly-fx.xlsx` (a long FX time series)
   becomes a **380-page** PDF and ~364 KB of Markdown — four-column rows
   flattened to four lines each, tens of thousands of loose number lines with
   no table structure. Technically lossless, practically unusable, and it costs
   pipeline time proportional to the explosion.

Ruled sheets are fine: `scb-amneslarare.xlsx` extracts 14 clean Markdown tables
with correct cells (verified by hand).

## Root cause

- LibreOffice paginates a sheet into print pages; the PDF table detector (T-031)
  is conservative and keys on ruled borders, which many spreadsheets lack.
- Nothing in the pipeline knows the input *was* a spreadsheet, so no
  spreadsheet-appropriate handling (sheet = one table) can kick in.

## Options

1. **Route xlsx around the PDF detour for tables**: read cell data directly
   (`openpyxl` as an Office-variant-only dependency) and emit one Markdown
   table per used sheet range, while still using the LO-PDF path for charts/
   figures. Honest representation for data sheets; adds a dependency to the
   Office image only.
2. **Teach the table detector borderless mode for spreadsheet-born PDFs**
   (alignment-based column inference, gated on the known input format). Keeps
   one path; borderless column inference is exactly what T-050 deferred as
   hard.
3. **Guardrails only**: cap/warn on page explosion (e.g. loud warning above N
   pages for a spreadsheet) and document that borderless sheets flatten.
   Cheapest; does not fix attribution.

Option 1 pairs naturally with the T-054 Office image variant; bench any table
work on the corpus's labelled sheets first (T-030 template).

## Acceptance criteria

- [x] A decision (with bench numbers for whichever extraction path is chosen)
      on borderless-sheet handling — **openpyxl (Option 1)**, numbers above.
- [x] `ons-accessible-tables.xlsx` yields structured tables (or a recorded,
      justified decision not to) — **recorded justified deferral**: openpyxl is
      the chosen extractor, but the coexistence-with-charts + dependency work is
      a scoped follow-up (bench captured so it starts informed).
- [x] A huge single-sheet workbook does not silently produce hundreds of pages
      of loose numbers — **loud, documented limit** (the page-explosion warning
      in `office.py`, + README "Known limitations").

## Follow-up (scoped, not in this ticket)

Implement the openpyxl spreadsheet-native table path (Office-variant-only
dependency): one Markdown table per used sheet range, row-capped with a loud
truncation notice, running *alongside* the LO-PDF path so embedded charts are
still detected/described. Needs a fidelity bench on the corpus's labelled
sheets (T-030 template) and the dependency justified in that PR.
