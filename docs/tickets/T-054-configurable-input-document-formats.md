# T-054: figmark accepts only PDF — no way to configure other document formats (Word/Excel/PPT/EPUB)

**Status:** Open — **direction decided (2026-07-02):** aim for **high-fidelity MS
Office** via **LibreOffice headless** (Option 2), *paired with* a hardened, scanned
and reviewed image (see "Decision" and "Security requirements"). EPUB and the other
PyMuPDF-native formats remain the free first tranche.
**Priority:** Medium

## Symptom

figmark only accepts PDF. Both HTTP surfaces reject anything else:

- `/v1/convert` gates on extension/content type
  ([api.py:348](../../src/figmark/api.py)) → `415 "Only PDF uploads are supported"`.
- `/v1/ocr` (the LibreChat backend, T-052) gates on the `%PDF` magic bytes
  ([ocr_compat.py:233](../../src/figmark/ocr_compat.py)) → `415`.

A consumer with a corpus of Word, Excel, PowerPoint or EPUB documents has to
pre-convert every file to PDF before figmark will touch it. There is no way to
configure which document formats figmark will accept.

Scope note: this is about **document** formats (docx/xlsx/pptx/epub, …), **not**
raster image input (`image_url`) — that is a separate concern tracked as a deferred
item in T-052.

## Root cause

The input contract is hardcoded to PDF, and the pipeline is PDF-centric (it consumes
a PyMuPDF `Document`). Two things are missing:

1. **A configurable allowlist.** `config.yaml` has no `input:` section — the set of
   accepted formats is a constant in the request handlers, not a config knob.
2. **A path from non-PDF bytes into the pipeline.** How each format becomes something
   the pipeline can read differs sharply by format (see Options) — and figmark's whole
   value is preserving *layout and figures*, so a text-only extraction that drops
   charts would defeat the point.

## Impact

- Consumers must run their own pre-conversion step; friction and a second toolchain.
- As a LibreChat OCR backend (T-052), figmark looks **narrower than the default it
  replaces**: LibreChat's built-in `document_parser` already ingests docx/xlsx/pptx
  and more. A figmark instance that only takes PDF is a downgrade on format coverage
  (even while it is an upgrade on figure description).

## Options

Formats split cleanly into "nearly free" and "needs a heavy dependency":

1. **PyMuPDF-native formats first — EPUB, XPS, MOBI, FB2, CBZ (recommended first
   tranche).** `fitz.open()` already opens these; the pipeline consumes the resulting
   `Document` unchanged. The only work is making the input gate format-aware (drop the
   PDF-only extension check and the `%PDF`-only magic check, sniff the real type) and
   adding them to the allowlist. **No new runtime dependency; air-gap-safe.** Cheap,
   high-confidence win — EPUB is the headline format here.

2. **Office (docx/xlsx/pptx) via LibreOffice headless** (`soffice --convert-to pdf`).
   Highest fidelity — preserves layout, tables and embedded charts/figures, which is
   exactly what figmark then describes — and is air-gappable (runs locally). **But it
   is a heavy image dependency** (a LibreOffice install is hundreds of MB), in direct
   tension with the lean / air-gapped-image constraint. Per the "adding a runtime
   dependency needs an explicit, justified reason" rule, this needs a deliberate
   decision, ideally behind an image variant or an optional sidecar so the base image
   stays slim.

3. **Office via lightweight extractors** (`python-docx` / `openpyxl` / `python-pptx`,
   or `pandoc` / MarkItDown). Much lighter, but they extract text/structure and
   **lose page layout and usually drop embedded figures/charts** — so the output is no
   better than LibreChat's own `document_parser`, and figmark's differentiator (figure
   description) is gone. Rejected as the primary path for figure-bearing documents;
   possibly acceptable for spreadsheets, where "figures" are rare and a table/text
   extraction is the honest representation.

4. **Configurable allowlist (needed regardless of 1–3).** A new `input:` section in
   `config.yaml` — accepted mimetypes → handler — enforced by both `/v1/convert` and
   `/v1/ocr`, failing loud on an unsupported type with a message that names what *is*
   supported. This is the actual "configure more mimetypes" ask; it is orthogonal to
   which handlers exist and dovetails with the v0.2 config-driven pipeline direction.

## Decision (2026-07-02)

**Office → LibreOffice headless (Option 2). Not the lightweight extractors.** The
whole point of figmark is preserving layout, tables and embedded charts/figures so
the vision model can describe them; a text-only extraction (Option 3) throws that
away and would make figmark no better than LibreChat's `document_parser`. We accept
the heavier image **on the explicit condition** that it is matched by the security
work below — the dependency cost is justified by the fidelity goal, not waved
through. Option 1 (PyMuPDF-native, incl. EPUB) still ships first as the free tranche.

The dependency is only justified if the image stays **secure and auditable**. That
is a hard part of this ticket, not a footnote — a large binary that parses untrusted
Office documents is a real attack surface, so the bar is: *no worse than today's
Trivy/CodeQL posture, and the conversion is sandboxed.*

## Security requirements (LibreOffice image)

- **Trivy hard gate stays green.** figmark already fails CI on fixable HIGH/CRITICAL
  (`security.yml`, `release.yml`, `ignore-unfixed`). Adding LibreOffice must not
  breach that. Prefer the **minimal headless component set** (e.g. the
  `--writer/--calc/--impress` core, no Java/UI/base) over the full suite to keep the
  package and CVE surface small; keep the base digest-pinned and `apt-get upgrade`d.
- **Keep a lean PDF-only image.** Ship Office support as a **separate image variant
  (or optional layer)** so users who only need PDF/EPUB do not inherit LibreOffice's
  CVE surface. The slim image stays the default.
- **Sandbox the conversion.** Convert untrusted documents with: **no network**,
  **macros disabled** and no auto-exec, a locked-down throwaway user profile, a
  per-file **timeout + memory/CPU limit** with a hard kill of runaway `soffice`,
  isolated temp dirs, and the existing **non-root (`USER 10001`) + read-only rootfs**
  posture preserved. A conversion that trips a limit fails loud, it does not hang.
- **Adversarial-input tests.** A corpus of hostile/malformed inputs — macro-laden,
  embedded-OLE/DDE, external-reference, decompression-bomb, and truncated files —
  must be **rejected or safely contained** (no code execution, no outbound
  connection, no unbounded resource use), each asserted in tests.
- This hardening is substantial enough that implementation may spin it off into a
  dedicated companion ticket; the requirement is recorded here so the Office decision
  is never merged without it.

## Notes / constraints

- **Content-sniff, don't trust the extension.** The `%PDF` magic check must generalise
  to detect the real format (OOXML and EPUB are both ZIP/`PK\x03\x04` containers, etc.)
  so an extension/content mismatch fails loud rather than being mis-handled.
- **Bench before code** (project rule): for any Office path, measure fidelity — are
  figures preserved? tables? reading order? — on a small labelled set of real
  docx/xlsx/pptx before committing to a heavy dependency. Record the numbers in the PR.

## Acceptance criteria

- [ ] A config-driven allowlist of accepted input formats; an unsupported upload gets
      a clean `415` that names the supported set (both `/v1/convert` and `/v1/ocr`).
- [ ] The input gate sniffs actual content (not just `%PDF` / extension) and fails
      loud on an extension/content mismatch.
- [ ] EPUB (and the other PyMuPDF-native formats) work end-to-end through the pipeline
      — the cheap, no-dependency tranche — with a bench note.
- [x] A recorded decision on Office handling: **LibreOffice headless for
      high-fidelity MS Office** (see "Decision"), conditional on the security work.
- [ ] MS Office (docx/xlsx/pptx) converts via LibreOffice headless and round-trips
      through the pipeline with a **fidelity bench** — figures/tables/reading order
      preserved — recorded in the PR (bench-before-code).
- [ ] **Office support ships as a separate/opt-in image variant**; the default image
      stays PDF/EPUB-only and does not inherit LibreOffice's CVE surface.
- [ ] **Trivy hard gate is green on the Office image** (fixable HIGH/CRITICAL = 0),
      and CodeQL stays clean — the security posture is no worse than today's.
- [ ] The conversion is **sandboxed**: no network, macros disabled, per-file timeout
      + resource limit with a hard kill, non-root + read-only rootfs preserved.
- [ ] **Adversarial-document tests** (macro/OLE/DDE/external-ref/decompression-bomb/
      truncated) prove hostile inputs are rejected or safely contained — no code
      execution, no outbound connection, no unbounded resource use.
