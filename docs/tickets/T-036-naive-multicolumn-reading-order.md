# T-036: Reading order is naive for multi-column pages

**Status:** Open
**Priority:** Medium — interleaved text on two-column pages; affects T-031
**Source:** External code review (2026-06-24), verified against the code.

## Symptom

Blocks are ordered by `(round(bbox.y / 10), bbox.x)` —
[pdf_loader.py:150](../../src/figmark/pdf_loader.py) and the re-sort after diagram
insertion at [pipeline.py:302](../../src/figmark/pipeline.py). On a two-column
page, a right-column block at the same y-band as left-column text sorts *between*
the left-column blocks, interleaving the two columns in reading order.

## Root cause

A single global y-then-x sort has no notion of columns; the `round(y/10)` row
quantisation makes any two blocks sharing a y-band sort purely by x, left-to-right
across the whole page width.

## Impact

Central-bank reports and academic papers are frequently two-column, so the output
is likely already subtly interleaved on those pages. The eval never tested
reading-order fidelity, so this has gone unmeasured. It also directly affects
[T-031](T-031-conservative-table-extraction.md): a `TableBlock` enters the *same*
sort, so a table in one column of a two-column page would be mis-placed.

## Options

1. **Column detection** — cluster block x-positions into columns, order within each
   column, then concatenate columns left-to-right.
2. **Use PyMuPDF's own sort** — `get_text(sort=True)` / the `"blocks"` sort flag /
   `TextPage` ordering, which already has column-aware heuristics.
3. Heuristic: split the page at the dominant interior x-gap, order left column then
   right.

Recommendation: evaluate PyMuPDF's own sort first (cheap, already a dependency);
fall back to explicit column clustering if it is insufficient.

## Acceptance criteria

- [ ] A two-column fixture (figure + text) produces correct reading order.
- [ ] Single-column pages are unchanged.
- [ ] `TableBlock` placement (T-031) is validated on a two-column page.
- [ ] Reading-order fidelity is added as a checked case to the eval.
