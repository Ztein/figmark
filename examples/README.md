# Example documents

figmark's tests and demos run against real PDFs. To keep the repository small and
avoid vendoring third-party documents, the sample PDFs are **not committed** —
fetch them locally instead.

```bash
python examples/download_samples.py                  # paper.pdf + scanned.pdf
python examples/download_samples.py --include-large   # also long.pdf (27 MB)
```

This downloads the small samples by default. The PDF-based tests resolve documents
from `examples/` first, then from a local `testfiler/` directory, and otherwise
skip.

## The samples

| File          | What it is                                       | Used by                                  |
|---------------|--------------------------------------------------|------------------------------------------|
| `paper.pdf`   | An open-access paper with raster figures         | document-agnostic paper tests, demo      |
| `scanned.pdf` | An image-only scan (no text layer)               | document-agnostic OCR-classification tests |
| `long.pdf`    | A 526-page report (opt-in, 27 MB)                | document-agnostic pagination/scale tests |
| `report.pdf`  | A report with vector charts (optional, local)    | diagram-pipeline tests *(calibrated)*    |
| `guide.pdf`   | A document with a large cover image (optional, local) | OCR + image-resize tests *(calibrated)*  |

`paper.pdf` is fetched from [arXiv](https://arxiv.org/abs/1505.04597) (U-Net,
Ronneberger et al., 2015). The paper-based tests assert only document-agnostic
invariants (text is extracted, at least one image is found, reading order holds),
so any paper with embedded figures works.

`scanned.pdf` is a *genuinely scanned* document: every page is a full-page raster
image with no extractable text, so figmark classifies it as scanned and runs the
OCR pipeline (Tesseract first, vision-OCR fallback). It is derived from a
public-domain NASA scan (see *Provenance* below) by re-rendering its pages as
images only — exactly what a scanner without OCR produces. Because the source is
English, transcribing it well needs an English Tesseract pack; override the
Swedish default with `ocr.language: eng` (and `brew install tesseract-lang`).

`long.pdf` is a 526-page report. It is opt-in because of its size; the tests that
use it only sample pages, so they stay fast.

### Optional: report.pdf and guide.pdf

A few tests are *calibrated* to specific documents (e.g. "two charts on page 11").
These are skipped unless you provide matching files. To run them, drop a
chart-heavy report at `examples/report.pdf` and a scanned-style document with a
large cover image at `examples/guide.pdf`. Swedish public-authority reports (for
example a Riksbank monetary-policy report) are a good fit for the vector-chart
pipeline.

## Try it

```bash
python examples/download_samples.py
figmark examples/paper.pdf
# → output/paper/paper.md  (Markdown with figure descriptions)

figmark examples/scanned.pdf
# → classified as scanned; runs the OCR pipeline
```

> Running figmark calls a vision model and needs `FIGMARK_API_KEY` in `.env`.
> See the top-level [README](../README.md).

## Provenance

| File          | Source                                                                 | License            |
|---------------|------------------------------------------------------------------------|--------------------|
| `paper.pdf`   | [arXiv 1505.04597](https://arxiv.org/abs/1505.04597) (U-Net)           | arXiv non-exclusive |
| `scanned.pdf` | NASA Apollo Experience Report ([NTRS 19760026143](https://ntrs.nasa.gov/citations/19760026143)) | US Gov public domain |
| `long.pdf`    | NASA Apollo Program Summary Report ([NTRS 19750013242](https://ntrs.nasa.gov/citations/19750013242)) | US Gov public domain |

## Licensing note

Downloaded documents keep their original licenses and are for local testing and
demonstration only. They are intentionally not redistributed as part of this
repository.
