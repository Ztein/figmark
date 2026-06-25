# T-044: Hyperlinks are dropped and footnotes interrupt the body text

**Status:** Open
**Priority:** Medium — links carry meaning; inlined footnotes break sentence flow

## Symptom

Two related losses in the text representation:

1. **Hyperlinks are dropped.** A link embedded in the PDF keeps its visible text in
   the output but loses its URL — `see our [report](https://…)` becomes just
   "see our report". Citations and references that point somewhere are flattened.
2. **Footnotes interrupt the body.** Footnote text (small font, bottom of the page)
   is emitted as an ordinary block at its bbox position, so it lands in the middle
   of the reading flow and breaks the sentence it footnotes.

## Root cause

`iter_page_blocks` ([pdf_loader.py](../../src/figmark/pdf_loader.py)) reads only
text spans. PDF link annotations (`page.get_links()`) are never consulted, so URLs
never reach the output. Footnote blocks are small-font, bottom-margin text but are
treated as normal body blocks (overlaps with the position work in
[T-043](T-043-strip-running-headers-footers.md)).

## Impact

An LLM loses the destinations of links (often the meaningful part of a reference),
and footnote text mixed mid-paragraph degrades the readability and the fidelity of
the main text.

## Options

- **Hyperlinks:** read `page.get_links()`, map each link rectangle to the text
  spans it overlaps, and render `[text](url)` in the Markdown. Well-defined and
  low-risk.
- **Footnotes:** detect small-font blocks in the bottom margin band (reuse T-043's
  position signal) and either move them to an end-of-page / end-of-document notes
  section or mark them, rather than inlining them in the body.

Recommendation: do **hyperlinks first** (clean, fully specified by `get_links()`);
**footnotes second**, built on T-043's margin/position detection.

## Acceptance criteria

- [ ] PDF hyperlinks render as Markdown links carrying their URL.
- [ ] Footnote text no longer interrupts body paragraphs (moved to a notes section
      or otherwise segregated).
- [ ] Body text without links/footnotes is unchanged.
- [ ] Offline tests for both: a link-bearing page and a footnote-bearing page.
