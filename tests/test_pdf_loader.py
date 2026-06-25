from __future__ import annotations

from pathlib import Path

import fitz

from figmark.pdf_loader import (
    ImageBlock,
    TextBlock,
    _linkify,
    is_scanned,
    iter_page_blocks,
    iter_pages,
    open_pdf,
    sort_blocks_reading_order,
)


def test_linkify_wraps_anchor_as_markdown():
    links = [(fitz.Rect(0, 0, 500, 20), "https://example.com/", "https://example.com/docs")]
    out = _linkify("Visit https://example.com/ for more", (0, 0, 500, 20), links)
    assert "[https://example.com/](https://example.com/docs)" in out


def test_linkify_is_whitespace_tolerant_across_line_breaks():
    links = [(fitz.Rect(0, 0, 500, 40), "github com", "https://github.com")]
    out = _linkify("see github\ncom now", (0, 0, 500, 40), links)
    assert "[github com](https://github.com)" in out


def test_linkify_ignores_links_outside_the_block():
    links = [(fitz.Rect(0, 700, 500, 720), "footer link", "https://x.test")]
    out = _linkify("body text without that anchor", (0, 0, 500, 20), links)
    assert out == "body text without that anchor"  # link rect doesn't overlap the block


def test_pdf_hyperlink_becomes_markdown_link(tmp_path: Path):
    """A URL link embedded in the PDF survives extraction as a Markdown link. (T-044)"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "See the manual here for details.", fontsize=11)
    rect = page.search_for("here")[0]
    page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": "https://example.com/manual"})
    out = tmp_path / "linked.pdf"
    doc.save(out)
    doc.close()

    d = open_pdf(out)
    try:
        text = " ".join(b.text for b in iter_page_blocks(d[0]) if isinstance(b, TextBlock))
    finally:
        d.close()
    assert "[here](https://example.com/manual)" in text


def test_single_column_reading_order_is_plain_y_then_x():
    """A single-column page has no wide left-edge gap, so ordering is the same
    plain (y, x) flow as before — no behaviour change. (T-036)"""
    blocks = [
        TextBlock(bbox=(50, 300, 540, 320), text="C"),
        TextBlock(bbox=(50, 100, 540, 120), text="A"),
        TextBlock(bbox=(50, 200, 540, 220), text="B"),
    ]
    sort_blocks_reading_order(blocks, page_width=595)
    assert [b.text for b in blocks] == ["A", "B", "C"]


def test_two_column_reading_order_not_interleaved():
    """On a two-column page, the left column is read top-to-bottom before the
    right column — not interleaved by y across both. (T-036)"""
    blocks = [
        TextBlock(bbox=(50, 100, 290, 120), text="L1"),
        TextBlock(bbox=(320, 100, 560, 120), text="R1"),
        TextBlock(bbox=(50, 140, 290, 160), text="L2"),
        TextBlock(bbox=(320, 140, 560, 160), text="R2"),
    ]
    sort_blocks_reading_order(blocks, page_width=595)
    assert [b.text for b in blocks] == ["L1", "L2", "R1", "R2"]


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
