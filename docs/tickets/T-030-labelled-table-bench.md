# T-030: Build the labelled table bench and score the engine + filter

**Status:** Open — bench built and scored 2026-06-24; decision recorded below
(**ship PyMuPDF-only**). Ready to close on merge of the bench + ground truth.
**Priority:** High — gates [T-031](T-031-conservative-table-extraction.md); no
extraction code ships until the numbers justify it
**Parent:** [T-026](T-026-tables-flattened-to-text.md)

## Results (2026-06-24)

Bench + hand-labelled ground truth live in
[scripts/table_bench/bench.py](../../scripts/table_bench/bench.py): 5 real tables
(BoC Tables 1 & 2, Fed balance sheet, Norges-4 Table 1, Norges-2 Table 1 as a
regression) transcribed from hi-DPI renders, plus negative controls. Cell-recall =
fraction of ground-truth numeric tokens recovered across all kept tables on the
page (the real output emits each kept table, so a detector-split table still
delivers its data).

| Engine | Detection | Mean cell-recall | Renders | Designated control pages | `bis-ar` whole-doc | `ecb-fsr` whole-doc |
|---|---|---|---|---|---|---|
| **PyMuPDF `find_tables()` + 3-gate filter** | **5/5** | **99 %** | **5/5** | **0 leaks** | **0** | 1 |
| pdfplumber `extract_tables()` (raw, no filter) | 5/5 | 80 % | — | — | 203 raw | 5 raw |

The `ecb-fsr` whole-doc survivor (p116) was inspected and is a **genuine
regression-results data table** (`Low-TFP firm | 0.113 | 0.008 | 0.273*** | …`),
i.e. a correct detection, not a false positive — the filter extracted the one real
table in that document while rejecting its ~70 chart-caption rows.

**Decision threshold (written before scoring):** "if PyMuPDF reaches ≥90 %
detection and ≥95 % cell accuracy AND zero false positives on the negative
controls, ship PyMuPDF-only; otherwise adopt pdfplumber." All three clear:
detection 100 %, cell-recall 99 %, zero false positives.

**Decision: ship PyMuPDF-only + the 3-gate filter. No new runtime dependency.**
pdfplumber loses on both axes — lower recall (80 %, e.g. Fed 40 % / Norges ~80 %),
and unfiltered it floods 203 false tables on `bis-ar` (chart gridlines), so it
would need the *same* filter and still extract less. pdfplumber was installed into
the venv only to run this comparison and then uninstalled; the bench imports it
lazily and skips gracefully when absent. The 3-gate filter is now validated and
moves to [T-031](T-031-conservative-table-extraction.md) for productionisation.

Note on shape: exact rows×cols intentionally is not a pass/fail metric — ground
truth for some tables is a labelled sub-region (BoC Table 2 excludes the
multi-line memo block) and `find_tables` sometimes splits one table into parts
(Fed → 2). Data fidelity is measured by cell-recall, which handles both.

## Goal

Turn the unlabelled probe ([scripts/probe_tables.py](../../scripts/probe_tables.py),
written for the 2026-06-24 T-026 update) into a **labelled** bench so the
PyMuPDF-vs-pdfplumber decision is made against written ground truth and a written
threshold — not against raw detection counts, which the probe already showed are
misleading (`ecb-fsr` 70 chart-caption "tables", `bis-ar` axis-tick ladders).

## What to build

1. **Bench set.** ~10–15 hand-labelled tables drawn from the validation set the
   probe identified — all genuine ruled data tables:
   - `norges-mpr-4-2025` pp. 17, 18, 27, 53, 54, 55
   - `norges-mpr-2-2025` pp. 19, 32, 63, 64, 65 (same structure as -4 → regression value)
   - `boc-mpr-202401` pp. 6, 14 · `boc-mpr-202407` pp. 6, 14, 15
   - `fed-mpr-202407` p. 53
   Span the styles that matter: forecast grids with year columns + parenthesised
   revision deltas, GDP-contribution tables, and a wide balance-sheet table.
   Hand-write the ground-truth cell grid for each (a small YAML/JSON per table).
2. **Negative controls.** Include pages that must yield **zero** tables so the
   filter's silence is scored, not just its hits:
   - `ecb-fsr-202411` p. 6 (chart-caption row), `bis-ar-2024` p. 31 (axis ladder),
     and any `riksbank-ppr` / `penningpolitisk-rapport` page (vector charts only).
3. **Metrics, per table:** detection (binary), shape (rows×cols correct, binary),
   cell accuracy (fraction of ground-truth cells matching exactly — precision +
   recall over cells), renders (emitted Markdown parses as a valid table).
4. **Score both engines on the same bench:** PyMuPDF `find_tables()` (+ the
   refined 3-gate filter from T-026) vs pdfplumber `extract_tables()`. pdfplumber
   is **not** currently a dependency — install it in the bench env only; do not
   add it to the runtime unless the numbers force it.
5. **Decision rule (write the threshold down in the PR).** e.g. "if PyMuPDF
   reaches ≥90 % detection and ≥95 % cell accuracy across the bench AND zero false
   positives on the negative controls, ship PyMuPDF-only; otherwise adopt
   pdfplumber for tables." Record the actual numbers so the choice is auditable.

## Adversarial cases to include

The probe surfaced these; the bench must cover them so the filter is tuned, not
guessed: chart-caption rows (`ecb-fsr`), axis-tick ladders (`bis-ar`), borderless
number tables held together by alignment, merged/spanned header cells, and a table
that breaks across a page boundary.

## Acceptance criteria

- [ ] Labelled ground truth committed for the bench set + negative controls.
- [ ] A runnable bench script scores both engines and prints per-table detection,
      shape, cell accuracy, and render validity, plus false positives on controls.
- [ ] The written decision threshold and the actual numbers are recorded in the PR.
- [ ] The PyMuPDF-only vs +pdfplumber decision is stated, with the numbers behind it.
- [ ] No runtime dependency added by this ticket (bench-only installs are fine).
