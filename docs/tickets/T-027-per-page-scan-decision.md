# T-027: A scanned/image-only page inside a text PDF is never OCR'd (scan decision is document-level)

**Status:** Open
**Priority:** High — silent content loss on mixed documents

## Symptom

A PDF that is mostly text-encoded but contains one or more scanned / image-only
pages (a signed letter, a photographed appendix, an inserted scan) loses the text
of those pages entirely, with no warning. The output looks complete; the scanned
pages' content is simply absent.

## Root cause

The scanned/not decision is made **once for the whole document**.
[`is_scanned(doc)`](src/figmark/pdf_loader.py) returns a single boolean from the
*average* characters per page (`< SCANNED_MIN_AVG_CHARS_PER_PAGE = 50`), and that
one flag drives every page in [`convert`](src/figmark/pipeline.py): either the
entire document goes through Tesseract/vision-OCR, or the entire document goes
through direct text extraction. A scanned page in an otherwise-text document is on
the text path, where `get_text` yields little or nothing — and it is never OCR'd.
(There is partial mitigation: such a page's full-page image may still be extracted
and *described* by the vision model as a figure, but its text is not transcribed.)

This is silent data loss, which is exactly the failure class the project's
"fail loudly, no silent fallbacks" principle exists to prevent (cf. T-024).

## Impact

Mixed digital+scanned documents — common in real archives — come out with holes.
Nobody is told which pages were dropped. The averaging also cuts the other way: a
mostly-scanned document with a few dense text pages could be misclassified too.

## Options

1. **Per-page classifier.** Decide direct-text vs OCR per page from that page's own
   signals; keep the document-level number only as a logged hint. Loudly flag every
   page that switches to OCR. Needs a guard so genuinely sparse pages (section
   dividers, full-page figures, blanks) are not needlessly OCR'd — use an
   image-coverage signal: *low text **and** a near-full-page image* ⇒ scanned page
   ⇒ OCR; *low text and no large image* ⇒ legitimately sparse ⇒ leave it.
2. **Minimal per-page rescue.** Keep the document-level default, but add: if a page
   in a text-classified doc has `< threshold` chars **and** a large image covering
   most of the page, OCR just that page. Smaller change, same guard, less general.
3. **Detect-and-warn only.** Run the per-page check and emit a loud warning for
   suspect pages without auto-OCR, leaving a human to decide. Surfaces the problem
   but does not fix the output.

Recommendation to evaluate: **Option 1** (a real per-page decision) with the
image-coverage guard. This also establishes the natural extension point for a
*quality* axis (detecting present-but-garbled text → OCR), tracked separately.

## Acceptance criteria

- [ ] The decision is per page: a scanned page inside a text PDF is OCR'd and its
      text appears in the output.
- [ ] A genuinely sparse page (divider / figure-only / blank) is **not** needlessly
      OCR'd.
- [ ] Every per-page OCR decision (and its reason) is logged loudly.
- [ ] `is_scanned` is retained only as a fast-path/hint, or removed — no behaviour
      depends on a single document-wide flag.
- [ ] Validated on a mixed-content fixture (text pages + at least one scanned page).
- [ ] A note records how this interacts with the document-summary/language steps
      (which sample leading text).
