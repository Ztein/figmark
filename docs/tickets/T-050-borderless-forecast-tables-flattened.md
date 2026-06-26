# T-050: Borderless forecast tables are flattened, scrambling column↔value attribution

**Status:** Open — **investigated 2026-06-26; detection fix deferred, limitation
documented** (see "Investigation" below). The README "Tables" note now states the
real flatten failure mode and *why* we keep raw text instead of guessing a grid.
**Priority:** Medium — known-gap honesty now; a detection fix is deferred until a
real-use-case impact signal justifies it.

## Symptom

A downstream consumer (a document-retrieval ingestion pipeline) ran `/v1/convert`
against `riksbank-ppr-202512` pp. 64–65 ("Prognostabeller") and got **0 Markdown
table rows**. "Tabell 1. Styrränteprognos" was flattened so that the row label and
each cell value landed on *separate lines* (`Styrräntan` → `2,00 (2,00)` →
`1,75 (1,75)` → …), and the **column headers (`2025kv3 … 2028kv4`) were decoupled
and dumped at the bottom of the page**. The column (quarter) ↔ value association is
therefore lost in the text.

## Root cause

This is **not** a regression in the table feature (T-026/T-030/T-031) — it is a
**blind spot in that feature's bench**:

- The shipped extractor is PyMuPDF `find_tables()` + a deliberately conservative
  3-gate filter ([T-031](T-031-conservative-table-extraction.md)). `find_tables`
  relies on **ruling lines / clear whitespace structure**.
- The bench's 99 % cell-recall ([T-030](T-030-labelled-table-bench.md)) was scored
  only on **ruled** tables (Norges/BoC/Fed). Riksbank was used there as a
  **negative control** — `riksbank-ppr-202503.pdf` p. 10, a *vector-chart page*
  that must stay silent ([scripts/table_bench/bench.py:200](../../scripts/table_bench/bench.py)).
- The forecast appendix tables in the **December** issue (pp. 64–65) are a genre we
  never put in the positive ground truth: **borderless**, whitespace-aligned
  forecast grids. `find_tables` does not detect them, so they fall through to the
  text path and get flattened.

So "Riksbank stays silent = good" (a chart page) and "Riksbank forecast tables are
flattened = bad" (an appendix data table) are about *different pages of different
issues* — both true, no contradiction.

## Impact

- **Quantitative-lookup retrieval** (pulling figures back out of tables) is at risk
  at the ingestion layer for borderless-table documents: the numbers survive, but
  the temporal/column attribution is broken, so a downstream model can answer with
  the wrong quarter.
- The README **already** lists borderless/spanning tables as unhandled, but
  undersells the failure: it reads as "not reconstructed" when the real behaviour
  is **actively scrambled** (label and values on separate lines, headers detached).

## Position (why we are not rushing a detection fix)

The output is almost always read by a **downstream LLM**, not a human or a strict
parser. A flattened-but-complete table is often still recoverable by that model —
especially with the `<!-- page N -->` markers preserved for provenance. The
honest, lean move is:

1. **Know exactly where we fail** — reproduce and measure, don't guess.
2. **Document the limitation loudly** so consumers can mitigate (page markers,
   source-page pointer, or a separate table extractor for number-heavy reports).
3. **Let the downstream consumer measure the real-use-case impact.** If borderless
   tables turn out not to materially hurt answer quality, an expensive detection
   change isn't justified yet.
4. Revisit a sustainable detection strategy later, *if* the impact signal warrants
   it — gated by the project's "bench before code" rule.

This matches our principles: fail loud (document the gap, don't hide it), stay
lean (no speculative detection rework), bench before code.

## Options (for the eventual detection fix — deferred, not chosen)

1. **Add a whitespace/text detection strategy** (PyMuPDF `find_tables`
   `strategy="text"`, or column-clustering on span x-positions). Catches borderless
   grids — but risks re-introducing the false-positive flood the 3-gate filter was
   built to suppress (`bis-ar` produced 203 raw false tables). Would need the gates
   re-validated against the new strategy.
2. **A dedicated table extractor for number-heavy reports** (e.g. a second pass
   only on pages whose text path shows a value-ladder shape). More moving parts.
3. **Do nothing in code; rely on the downstream LLM + page markers** and the README
   note. Cheapest; the current recommendation until impact data says otherwise.

## Investigation (2026-06-26)

Probed the reported pages directly (`examples/eval/riksbank-ppr-202512.pdf`, pp.
64–65 = 0-indexed 63–64), running each candidate through figmark's actual 3-gate
`keep_table` filter:

| Page | `find_tables()` (lines — what we ship) | `strategy="text"` (whitespace) |
|---|---|---|
| 64 (Tabell 1 Styrränta) | **0 candidates** → flattened | 1 candidate, **passes the gates** (61×5) |
| 65 (Tabell 2 Inflation …) | **0 candidates** → flattened | 1 candidate, **passes the gates** (51×9) |

So the flatten is confirmed: the shipped lines strategy detects **nothing** on
these borderless pages.

**The text strategy is not a safe fix — not because of false positives, but
because the extraction is garbled.** Two findings:

1. **False-positive flood did *not* materialise.** The 3-gate filter held under the
   text strategy on the chart-heavy negative controls: `riksbank-ppr-202503` p. 10
   (vector chart) → 0 kept; `bis-ar-2025` and `ecb-fsr-202411` first 50 pages → 0
   kept under text strategy (vs the 203 *raw* pdfplumber tables T-030 warned about).
   The gates are robust to the strategy change.
2. **But the grid it extracts asserts a wrong structure.** On p. 64 the text
   strategy returns one 61×5 grid that (a) **merges two distinct tables** (Tabell 1
   Styrränta + Tabell 2 Inflation) into one, (b) **chops the label column
   mid-word** (`abell 1. Styrr`, `rocent`, `älla: Riksbank`), and (c) **splits cell
   boundaries through numbers** (`2,00 (2,00)` → `2,0` + `,00 …`) and merges
   adjacent quarters (`2026kv4 2027kv` in one header cell). Rendered as Markdown
   this is a confident but **wrong** column↔value mapping — strictly worse than the
   honest flattened text, which at least preserves the raw tokens for a downstream
   model to interpret.

The clean fix would need real column-boundary detection for proportional-font,
borderless, multi-table appendix pages. PyMuPDF itself points at its
`pymupdf_layout` package for exactly this — a **new runtime dependency**, which the
lean / air-gapped-image constraint rules out without an explicit justification.

## Decision (2026-06-26)

**Defer the detection fix; document the limitation.** Option 1 (text strategy) is
rejected — it produces a wrong-structure table, the opposite of the data-fidelity
goal. Options 1′/2 (proper borderless column detection, or `pymupdf_layout`) are a
real project with a dependency cost and a precision bench, not justified until the
downstream consumer's real-use-case data shows borderless tables actually hurt
answer quality. Until then we **keep raw text and say so loudly** (README + this
ticket). Re-open the build decision when that impact signal arrives.

## Acceptance criteria

- [x] Reproduce: confirmed lines-strategy detection is 0 on `riksbank-ppr-202512`
      pp. 64–65 (the gap is now a measured number, not an anecdote). A full labelled
      cell-recall transcription is left for the eventual fix — the 0-detection
      result already settles the "defer or build" decision.
- [x] README "Tables" limitation describes the actual **flatten** failure mode and
      *why* we keep raw text instead of guessing a structure.
- [x] A decision is recorded (above): defer; trigger is downstream real-use-case
      impact, not code committed in this ticket.
