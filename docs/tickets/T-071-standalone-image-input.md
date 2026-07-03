# T-071: figmark can't take a standalone image as input — a raster image is rejected, though its whole engine is figure interpretation + OCR

**Status:** Open
**Priority:** Medium — this is the rare gap where reach, product thesis, and low
cost all point the same way: a raster image maps exactly onto machinery figmark
already has, and it is also a documented Mistral OCR input type (`image_url`) we
currently reject.

## Symptom

figmark accepts documents (PDF, EPUB/native, Office) but **not a standalone
raster image**. A PNG/JPG/… is not in `SUPPORTED_FORMATS`
([input_formats.py](../../src/figmark/input_formats.py):
`NATIVE_FORMATS | OFFICE_FORMATS`, no image types), so:

- the CLI and `/v1/convert` reject it;
- over `/v1/ocr`, a `document.image_url` is resolved to bytes but then fails the
  format gate (`gate_document_format` against `cfg.input.formats`) → **415**.
  This is the T-052 deferred item ("raster image input via `image_url`"), never
  given its own ticket.

## Root cause

The pipeline consumes a PyMuPDF `Document`, and the input contract only lists
page-based document formats. Nothing bridges "a single image" into the pipeline
— even though PyMuPDF opens common raster formats directly as a one-page
document, and the pipeline *already* decides, per page/region, whether to
**interpret** (chart/diagram/photo → vision description) or **OCR** (scanned
text → Tesseract + vision rescue). The capability exists; the input form is just
not admitted.

## Why this is worth doing (and on-thesis)

An image is simply *a one-page document that is entirely one figure*. So this is
**not a new capability — it exposes an existing one to a new input form:**

- **Plays to figmark's strength.** The differentiator is figure interpretation;
  a loose chart/diagram/photo is precisely what figmark interprets best.
- **The interpret-vs-OCR choice is already made for us.** The per-page decision
  machinery answers "OCR the text or interpret the picture?" — no new branch to
  design; the same logic a PDF page goes through.
- **Low cost.** Open the raster as a one-page doc (fitz handles png/jpg/…) and
  run the existing pipeline. No new model, no new infrastructure.
- **Three wins align:** on-thesis value, Mistral-contract parity (`image_url` is
  a documented input type), and near-zero cost — unlike the Annotations gap
  (T-070, iced) where at best only parity applied, at a cost.

## Impact

- A RAG/ingestion pipeline feeding figmark loose screenshots, chart images, or
  photographed pages gets figmark's *interpretation* ("this is a bar chart of X
  with values Y") instead of OCR noise or a rejection.
- Closes the last deferred piece of the `/v1/ocr` document contract on the input
  side.

## Honest limitation (state it, don't hide it)

For **messy scanned text** in an image, figmark's OCR is Tesseract + a
vision-model rescue, **not a VLM-grade OCR** — weaker than Mistral's model on
noisy scans and handwriting (the same limitation already documented for scanned
PDFs). So image input **shines on figures/diagrams/photos and inherits the known
OCR weakness on messy scans** — the usual figmark profile, not a new weakness.
Market and document it that way; do not claim VLM scan fidelity.

## Options

1. **Admit raster formats into the input gate + open as a one-page document.**
   Add the image types to the allowlist (sniffed by content, like every other
   format, T-054), open the bytes as a one-page PyMuPDF document, and run the
   existing pipeline (which interprets or OCRs per its normal decision).
   Smallest change; reuses everything. Wire it into the CLI, `/v1/convert`, and
   `/v1/ocr` (removing the `image_url` 415).
2. **Force one behaviour.** Always-OCR or always-describe the image regardless
   of content. Simpler to reason about but throws away the very decision logic
   that makes figmark good on mixed content — rejected as the default.
3. **`image_url` only (OCR surface), not the CLI/convert.** Narrower scope if we
   only care about Mistral parity. Cheaper, but leaves the CLI/`/v1/convert`
   asymmetric for no real reason once Option 1's plumbing exists.

Option 1 is the on-thesis, symmetric choice; the per-content interpret-vs-OCR
decision is figmark's whole point and should apply to images too.

## Acceptance criteria

- [ ] A standalone raster image (PNG/JPG at least) is accepted on the CLI,
      `/v1/convert`, and `/v1/ocr` (`image_url` no longer 415s), gated by the
      same content-sniffing allowlist as other formats.
- [ ] A chart/diagram image is **interpreted** (vision description) and a
      text-only scanned image is **OCR'd** — the existing per-content decision
      applies, verified on one of each.
- [ ] The scan-fidelity limitation is documented in the README (image input is
      for figures/diagrams/photos; not VLM-grade on messy scans).
- [ ] Offline tests cover an image-in → described/​OCR'd-out round-trip on both
      surfaces.
