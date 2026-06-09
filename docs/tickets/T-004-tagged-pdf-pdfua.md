# T-004: Tagged PDF / PDF/UA — real accessibility via the structure tree

**Status:** Open
**Priority:** Medium — builds on top of T-005 (annotation MVP)
**Requested:** 2026-05-20

## Symptom / motivation

T-005 (text annotations) gives the descriptions a visible and readable form in the PDF, but that isn't "real" accessibility according to the PDF/UA standard. Screen readers that follow the standard rely on the **structure tree** — every image should be a `<Figure>` element with an `/Alt` attribute. Annotations are a complement, not a replacement.

## Requirements

- The source PDF is "promoted" to a tagged PDF if it isn't already
- Each extracted image/chart becomes a `<Figure>` element in the structure tree
- The `/Alt` on each Figure contains the description
- Reading order is respected (the Figure elements sit in the right place in the text flow)
- The output validates against a PDF/UA checker (e.g. PAC, veraPDF)

## Options

### Option 1: pikepdf + manual structure tree
Add `pikepdf` as a dependency. Use its Pdf object-graph API to build `/StructTreeRoot`, `/ParentTree`, and Figure nodes. A lot of work but full control.

### Option 2: use an existing tool as a postprocess
Use `pdfua-tool` or similar (if one exists) as a CLI step after our pipeline. Outsource the complexity.

### Option 3: hybrid annotations + StructTreeRoot stub
Keep annotations (T-005) as the primary information carrier. Add a minimal StructTreeRoot that only ties the annotations to "figure" roles. Not full PDF/UA but closer.

## Recommendation

**Option 1 (pikepdf).** It's the "right" way according to the standard. Scales to future features like heading tags and language attributes.

## Acceptance criteria

- [ ] A `--tagged-pdf` flag that produces `<pdf>_tagged.pdf`
- [ ] PAC or veraPDF accepts the output as PDF/UA-conformant (at least for the Figure elements)
- [ ] VoiceOver/NVDA reads out the description when the user navigates to the image
- [ ] A live test that validates structure tree existence on a known PDF
