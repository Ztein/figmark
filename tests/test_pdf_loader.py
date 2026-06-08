from __future__ import annotations

from pathlib import Path

import fitz

from figmark.pdf_loader import (
    ImageBlock,
    TextBlock,
    is_scanned,
    iter_page_blocks,
    iter_pages,
    open_pdf,
)


def test_open_pdf_returns_document(paper_pdf: Path):
    doc = open_pdf(paper_pdf)
    try:
        assert len(doc) >= 1
    finally:
        doc.close()


def test_is_scanned_false_for_text_pdf(paper_pdf: Path):
    doc = open_pdf(paper_pdf)
    try:
        assert is_scanned(doc) is False
    finally:
        doc.close()


def test_is_scanned_true_for_rasterized_real_pdf(guide_pdf: Path, tmp_path: Path):
    """Rasterize 2 pages of the guide into an images-only PDF — it should be
    classified as scanned, since there is no extractable text."""
    src = fitz.open(guide_pdf)
    raster = fitz.open()
    try:
        for i in range(2):
            page = src.load_page(i)
            pix = page.get_pixmap(dpi=150, alpha=False)
            new_page = raster.new_page(width=pix.width, height=pix.height)
            new_page.insert_image(new_page.rect, pixmap=pix)
        raster_path = tmp_path / "rasterized_real.pdf"
        raster.save(raster_path)
    finally:
        raster.close()
        src.close()

    doc = open_pdf(raster_path)
    try:
        assert is_scanned(doc) is True
    finally:
        doc.close()


def test_iter_page_blocks_returns_text_and_images(paper_pdf: Path):
    doc = open_pdf(paper_pdf)
    try:
        text_blocks_total = 0
        image_blocks_total = 0
        for _, page in iter_pages(doc):
            blocks = iter_page_blocks(page)
            for b in blocks:
                if isinstance(b, TextBlock):
                    text_blocks_total += 1
                    assert b.text.strip()
                elif isinstance(b, ImageBlock):
                    image_blocks_total += 1
                    assert b.xref > 0, "ImageBlock must have a valid xref"
        assert text_blocks_total > 0
        assert image_blocks_total >= 1
    finally:
        doc.close()


def test_iter_page_blocks_image_xrefs_match_page_get_images(paper_pdf: Path):
    """Roundtrip: xrefs reported by iter_page_blocks must exist in page.get_images()."""
    doc = open_pdf(paper_pdf)
    try:
        found_match = False
        for _, page in iter_pages(doc):
            real_xrefs = {img[0] for img in page.get_images(full=True)}
            for b in iter_page_blocks(page):
                if isinstance(b, ImageBlock):
                    assert b.xref in real_xrefs, (
                        f"ImageBlock.xref={b.xref} not in page.get_images() {real_xrefs}"
                    )
                    found_match = True
        assert found_match, "Found no ImageBlocks at all — cannot verify xref matching"
    finally:
        doc.close()


def test_iter_page_blocks_reading_order(paper_pdf: Path):
    """Blocks should come in reading order: earlier y0 before later y0."""
    doc = open_pdf(paper_pdf)
    try:
        page = doc.load_page(0)
        blocks = iter_page_blocks(page)
        assert len(blocks) > 1
        # Sort by our own specification and compare.
        expected = sorted(blocks, key=lambda b: (round(b.bbox[1] / 10), b.bbox[0]))
        assert blocks == expected
    finally:
        doc.close()
