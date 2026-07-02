# T-056: Spreadsheet input — borderless sheets flatten to label/value soup and big sheets explode into hundreds of pages

**Status:** Open
**Priority:** Medium — xlsx is accepted input once T-054's Office tranche is
enabled, and *every* spreadsheet is wall-to-wall tables, so weaknesses that are
occasional for PDFs become the norm for xlsx.

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

- [ ] A decision (with bench numbers for whichever extraction path is chosen)
      on borderless-sheet handling.
- [ ] `ons-accessible-tables.xlsx` yields structured tables (or a recorded,
      justified decision not to).
- [ ] A huge single-sheet workbook does not silently produce hundreds of pages
      of loose numbers — either structured output or a loud, documented limit.
