# Example documents

figmark's tests and demos run against real PDFs. To keep the repository small and
avoid vendoring third-party documents, the sample PDFs are **not committed** —
fetch them locally instead.

```bash
python examples/download_samples.py
```

This downloads `examples/paper.pdf`. The PDF-based tests resolve documents from
`examples/` first, then from a local `testfiler/` directory, and otherwise skip.

## The samples

| File         | What it is                                   | Used by                                  |
|--------------|----------------------------------------------|------------------------------------------|
| `paper.pdf`  | An open-access paper with raster figures     | document-agnostic paper tests, demo      |
| `report.pdf` | A report with vector charts (optional)       | diagram-pipeline tests *(calibrated)*    |
| `guide.pdf`  | A document with a large cover image (optional) | OCR + image-resize tests *(calibrated)*  |

`paper.pdf` is fetched from [arXiv](https://arxiv.org/abs/1505.04597) (U-Net,
Ronneberger et al., 2015). The paper-based tests assert only document-agnostic
invariants (text is extracted, at least one image is found, reading order holds),
so any paper with embedded figures works.

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
```

> Running figmark calls a vision model and needs `BERGET_API_KEY` in `.env`.
> See the top-level [README](../README.md).

## Licensing note

Downloaded documents keep their original licenses and are for local testing and
demonstration only. They are intentionally not redistributed as part of this
repository.
