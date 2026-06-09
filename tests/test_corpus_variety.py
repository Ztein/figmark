"""Document-agnostic checks for the scanned and long corpus samples.

These assert only structural invariants (no API calls), so they run offline as
long as the samples have been fetched via examples/download_samples.py. If a
sample is missing the corresponding fixture skips.
"""

from __future__ import annotations

from pathlib import Path

from figmark.pdf_loader import (
    ImageBlock,
    TextBlock,
    is_scanned,
    iter_page_blocks,
    open_pdf,
)


def test_scanned_sample_is_classified_as_scanned(scanned_pdf: Path):
    """scanned.pdf is image-only, so the document classifier must flag it."""
    doc = open_pdf(scanned_pdf)
    try:
        assert len(doc) >= 1
        assert is_scanned(doc) is True
    finally:
        doc.close()


def test_scanned_sample_pages_are_full_page_images(scanned_pdf: Path):
    """Every sampled page is a single page-filling raster (i.e. a real scan)."""
    doc = open_pdf(scanned_pdf)
    try:
        for i in range(min(3, len(doc))):
            page = doc.load_page(i)
            assert page.get_text("text").strip() == "", "scanned page should have no text layer"
            max_cover = 0.0
            for img in page.get_images(full=True):
                for rect in page.get_image_rects(img[0]):
                    page_area = page.rect.width * page.rect.height
                    max_cover = max(max_cover, (rect.width * rect.height) / page_area)
            assert max_cover > 0.6, f"page {i + 1} is not dominated by a single image"
    finally:
        doc.close()


def test_long_sample_has_many_pages(long_pdf: Path):
    doc = open_pdf(long_pdf)
    try:
        assert len(doc) >= 100, "the long sample should have hundreds of pages"
    finally:
        doc.close()


def test_long_sample_loads_blocks_on_a_deep_page(long_pdf: Path):
    """The loader must extract blocks well past the first pages (no early bail)."""
    doc = open_pdf(long_pdf)
    try:
        deep = min(len(doc) - 1, 200)
        blocks = iter_page_blocks(doc.load_page(deep))
        assert any(isinstance(b, (TextBlock, ImageBlock)) for b in blocks)
    finally:
        doc.close()
