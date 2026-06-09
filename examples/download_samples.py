#!/usr/bin/env python3
"""Download the sample documents used by the examples and the test suite.

The curated corpus is intentionally varied so the pipeline is exercised against
representative real-world PDFs — a born-digital paper, a genuinely scanned
document, and a long report. The files are openly licensed but **not committed**
(see examples/README.md); fetch them locally with this script.

By default it fetches the small, document-agnostic samples that the offline test
suite runs against:

    paper.pdf    — open-access paper with embedded raster figures (arXiv)
    scanned.pdf  — image-only scan that triggers the OCR pipeline (NASA, PD)

The large sample is opt-in (it is a 27 MB, 526-page download):

    python examples/download_samples.py --include-large   # also fetches long.pdf

Usage:
    python examples/download_samples.py [--include-large]
"""
from __future__ import annotations

import io
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
USER_AGENT = "figmark-samples/0.1"

# Documents fetched verbatim. Each is openly licensed (see examples/README.md).
DIRECT = {
    # U-Net (Ronneberger et al., 2015) — born-digital paper with raster figures.
    "paper.pdf": "https://arxiv.org/pdf/1505.04597",
}

# Large, opt-in. Apollo Program Summary Report (NASA, US-gov public domain),
# 526 pages — a representative *long* document for pagination/scale.
LARGE = {
    "long.pdf": "https://ntrs.nasa.gov/api/citations/19750013242/downloads/19750013242.pdf",
}

# scanned.pdf is *derived*: we fetch a genuine public-domain NASA scan and
# re-render its pages as images only (dropping the OCR text layer), which is
# exactly what a scanner without OCR produces. The result averages ~0 extractable
# characters per page, so figmark classifies it as scanned and runs the OCR
# pipeline (Tesseract first, vision-OCR fallback). Source: NASA Apollo Experience
# Report (NTRS 19760026143), US-gov public domain.
SCANNED_SOURCE = (
    "https://archive.org/download/"
    "NASA_NTRS_Archive_19760026143/NASA_NTRS_Archive_19760026143.pdf"
)
SCANNED_PAGES = 14
SCANNED_DPI = 150


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        return resp.read()


def download(name: str, url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  {name} already present — skipping")
        return
    print(f"  {name} ← {url}")
    data = fetch(url)
    dest.write_bytes(data)
    print(f"    saved {len(data) // 1024} KB")


def build_scanned(dest: Path) -> None:
    """Fetch the public-domain scan and re-render it as an image-only PDF."""
    if dest.exists():
        print("  scanned.pdf already present — skipping")
        return
    import fitz  # PyMuPDF — already a figmark dependency

    print(f"  scanned.pdf ← rasterized from {SCANNED_SOURCE}")
    src = fitz.open(stream=io.BytesIO(fetch(SCANNED_SOURCE)), filetype="pdf")
    out = fitz.open()
    try:
        for i in range(min(SCANNED_PAGES, src.page_count)):
            pix = src[i].get_pixmap(dpi=SCANNED_DPI, alpha=False)
            page = out.new_page(width=pix.width, height=pix.height)
            page.insert_image(page.rect, pixmap=pix)
        out.save(dest, deflate=True, garbage=4)
    finally:
        out.close()
        src.close()
    print(f"    saved {dest.stat().st_size // 1024} KB ({SCANNED_PAGES} image-only pages)")


def main(argv: list[str]) -> int:
    include_large = "--include-large" in argv or "--all" in argv

    print("Downloading figmark sample documents into examples/ …")
    try:
        for name, url in DIRECT.items():
            download(name, url, HERE / name)
        build_scanned(HERE / "scanned.pdf")
        if include_large:
            for name, url in LARGE.items():
                download(name, url, HERE / name)
        else:
            print("  long.pdf skipped — pass --include-large to fetch it (27 MB)")
    except Exception as e:  # noqa: BLE001
        print(f"    failed: {e}", file=sys.stderr)
        return 1

    print("Done. See examples/README.md for the optional report.pdf / guide.pdf.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
