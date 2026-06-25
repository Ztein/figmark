# T-042: Output is a flat wall of paragraphs — headings and lists are lost

**Status:** Open
**Priority:** High — the single biggest lever for a faithful whole-document representation

## Symptom

`to_markdown` ([output.py](../../src/figmark/output.py)) emits every text block as a
plain paragraph. A report's title, section headings, sub-headings, and bulleted /
numbered lists all come out as undifferentiated paragraphs — no `#`/`##` headings,
no `-`/`1.` list markers. The document's outline and hierarchy are gone.

## Root cause

`iter_page_blocks` ([pdf_loader.py](../../src/figmark/pdf_loader.py)) keeps only a
block's text + bbox. The per-span font size, weight and flags that
`page.get_text("dict")` exposes — the signal that distinguishes a heading from body
text, or a list item from a paragraph — are discarded, so the output layer has
nothing to infer structure from.

## Impact

The representation is a wall of paragraphs. An LLM (or a human) loses sectioning,
hierarchy, and "what is a heading vs body" — exactly the structure that orients a
reader in a long document. It is also the foundation that will transfer to the
Word/PowerPoint work later (those formats are structure-first).

## Options

1. **Heuristic from typography.** Cluster span font sizes across the document;
   larger/bolder runs become headings (map size rank → `#`/`##`/`###`). Detect list
   items from leading bullet glyphs / numbering + indentation. Emit Markdown
   headings and lists. Bench: hand-label heading levels on a few documents and
   measure.
2. **Introduce an internal document model** — block types (`heading`, `paragraph`,
   `list`, `table`, `figure`) that PDF maps *into* and Markdown renders *out of*.
   More work now, but it becomes the shared abstraction for PDF/docx/pptx (the
   multi-format roadmap) instead of re-deriving structure per format.
3. Rely on any built-in PyMuPDF structure output (limited; worth checking but not
   sufficient alone).

Recommendation: ship **Option 1** first (bench-validated typography heuristic), and
let it grow into **Option 2**'s document model as the multi-format work begins —
the heading/list inference is the same regardless of which model holds it.

## Acceptance criteria

- [ ] On a labelled bench, headings render as Markdown headings with plausible
      levels; the numbers (precision/recall of heading detection) are recorded.
- [ ] Bulleted / numbered lists render as Markdown lists.
- [ ] Body paragraphs, figures and tables keep their current placement (no
      regression in reading order or figure/table embedding).
- [ ] A "good enough" bar is written down — we are not chasing 100 %, only a
      materially better outline than flat paragraphs.
