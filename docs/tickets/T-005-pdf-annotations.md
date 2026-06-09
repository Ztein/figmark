# T-005: Write descriptions into the PDF as text annotations

**Status:** Closed — implemented TDD-style 2026-05-20
**Priority:** Medium — MVP accessibility
**Requested:** 2026-05-20

## Symptom / motivation

Today we produce a `<name>.md` with the descriptions inlined. For users who actually want to read the PDF (not a text file) this is extra work. If we put the descriptions in as annotations directly in a copy of the PDF, screen readers have something to read and sighted users get visible popup notes.

## What gets built

- A new module `src/figmark/annotate.py` with `annotate_pdf(source, target, items)`
- Each description becomes a text annotation (`page.add_text_annot`) at the image's/chart's position
- The annotation `title` marks whether it is "Image" or "Chart"
- An `--annotate-pdf` flag in the CLI produces `output/<pdf>/<pdf>_annotated.pdf`

## Acceptance criteria

- [ ] The module is written TDD (tests before implementation)
- [ ] Test: the output PDF has one annotation per image + chart
- [ ] Test: annotation contents match the description byte-for-byte
- [ ] Test: annotation position sits on top of the source image's bbox
- [ ] Test: the annotated PDF can be opened and parsed by PyMuPDF
- [ ] Live test: the monetary policy report produces an annotated PDF with the right number of annotations
- [ ] CLI: `--annotate-pdf` flag, default off
