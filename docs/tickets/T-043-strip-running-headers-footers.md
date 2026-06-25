# T-043: Running headers, footers and page numbers leak into the body text

**Status:** Open
**Priority:** Medium — clean win; reduces noise and wasted tokens

## Symptom

Every page's running header, footer and page number is emitted as ordinary body
text. Across a 70-page report that is dozens of repeated lines (the document title,
a section name, "12", "13", …) interleaved into `<stem>.md` and `raw_text.txt`.

## Root cause

`iter_page_blocks` ([pdf_loader.py](../../src/figmark/pdf_loader.py)) returns **all**
type-0 text blocks; nothing classifies boilerplate that repeats at a consistent
position across pages, so margins are treated like body content.

## Impact

Noise in the representation, wasted tokens, and many repeated strings that can
mislead an LLM ("this phrase appears 70 times — it must be important"). It also
muddies reading order around page boundaries.

## Options

1. **Repetition + position.** A text block that recurs on many pages at a
   near-constant y-position inside the top/bottom margin band is a running
   header/footer → drop it (or tag it as a PDF/UA *artifact*, complementing
   [T-004](T-004-tagged-pdf-pdfua.md)). Page numbers: short numeric blocks in the
   margin band.
2. **Margin band only** — drop short blocks in the top/bottom N % of the page.
   Simpler but riskier (could eat a real first/last line).
3. Combine — require both repetition across pages *and* margin position before
   dropping, to protect real content.

Recommendation: **Option 3** (conservative). Bench on a real multi-page report:
confirm headers/footers/page numbers go and no body line is lost.

## Acceptance criteria

- [ ] Running headers/footers and page numbers are removed from the Markdown and
      raw text on a multi-page document.
- [ ] No body content is dropped (a precision check on a labelled page or two).
- [ ] A short single-page / no-boilerplate document is unaffected.
- [ ] Offline test on a synthetic doc with a repeated header + page numbers.
