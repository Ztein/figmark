# T-050: Borderless forecast tables are flattened, scrambling column↔value attribution

**Status:** Open
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

## Acceptance criteria

- [ ] Reproduce: add `riksbank-ppr-202512` pp. 64–65 to the labelled table bench as
      **positive** ground truth and record current cell-recall (expected ~0 %), so
      the gap is a written number, not an anecdote.
- [ ] README "Tables" limitation describes the actual **flatten** failure mode
      (row/value split, detached headers, lost column↔value link) and the
      mitigation (page markers / source-page pointer / downstream-LLM recovery).
- [ ] A decision is recorded on whether to attempt Option 1/2 now or defer, with
      the downstream consumer's real-use-case impact as the trigger — not committed
      to code in this ticket.
