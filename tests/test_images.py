from __future__ import annotations

from pathlib import Path

import fitz

from figmark.images import extract_images_from_page
from figmark.pdf_loader import ImageBlock, iter_page_blocks, iter_pages, open_pdf


def test_extract_images_writes_files(paper_pdf: Path, tmp_path: Path):
    doc = open_pdf(paper_pdf)
    out_dir = tmp_path / "images"
    try:
        total_extracted = []
        for page_num, page in iter_pages(doc):
            extracted = extract_images_from_page(doc, page, page_num, out_dir).images
            total_extracted.extend(extracted)
        assert len(total_extracted) >= 1
        for img in total_extracted:
            assert img.path.exists()
            assert img.path.stat().st_size > 0
            assert img.xref > 0
    finally:
        doc.close()


def test_extracted_images_match_pdf_loader_xrefs(paper_pdf: Path, tmp_path: Path):
    """Roundtrip: every ImageBlock from pdf_loader must map to an extracted image."""
    doc = open_pdf(paper_pdf)
    out_dir = tmp_path / "images"
    try:
        loader_xrefs: set[int] = set()
        extracted_xrefs: set[int] = set()
        for page_num, page in iter_pages(doc):
            for b in iter_page_blocks(page):
                if isinstance(b, ImageBlock):
                    loader_xrefs.add(b.xref)
            for img in extract_images_from_page(doc, page, page_num, out_dir).images:
                extracted_xrefs.add(img.xref)
        assert loader_xrefs <= extracted_xrefs, (
            f"ImageBlock xrefs not found by extract_images_from_page: "
            f"{loader_xrefs - extracted_xrefs}"
        )
    finally:
        doc.close()


def test_extract_images_filters_tiny_via_module_constant(
    paper_pdf: Path, tmp_path: Path, monkeypatch
):
    """Set the module-level constant absurdly high → no image passes."""
    import figmark.images as images_mod

    monkeypatch.setattr(images_mod, "MIN_IMAGE_WIDTH", 100000)
    monkeypatch.setattr(images_mod, "MIN_IMAGE_HEIGHT", 100000)

    doc = open_pdf(paper_pdf)
    out_dir = tmp_path / "images"
    try:
        total = []
        total_skipped = 0
        for page_num, page in iter_pages(doc):
            result = extract_images_from_page(doc, page, page_num, out_dir)
            total.extend(result.images)
            total_skipped += result.skipped_small
        assert total == []
        # The filtered images are reported (T-002), not silently dropped.
        assert total_skipped >= 1
    finally:
        doc.close()


def _pix() -> fitz.Pixmap:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
    pix.set_rect(pix.irect, (10, 200, 100))
    return pix


def test_referenced_but_not_drawn_images_are_skipped(tmp_path: Path):
    """LibreOffice-produced PDFs list every document image in each page's
    resource dict; only images actually *drawn* on the page may be extracted —
    otherwise a 6-image, 37-page document yields 222 phantom figures (T-054)."""
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_image(fitz.Rect(72, 72, 172, 172), pixmap=_pix())
    xref = page1.get_images(full=True)[0][0]

    # Page 2: same image in /Resources, but its content stream never draws it.
    page2 = doc.new_page()
    page2.insert_image(fitz.Rect(72, 72, 172, 172), xref=xref)
    for cont_xref in page2.get_contents():
        doc.update_stream(cont_xref, b" ")
    page2 = doc.reload_page(page2)
    assert page2.get_images(full=True), "precondition: the resource entry exists"

    result = extract_images_from_page(doc, page2, 2, tmp_path / "img")
    assert result.images == [], "an undrawn resource entry must not become a figure"
    assert result.skipped_not_drawn == 1, "the skip is reported, not silent (T-002)"

    kept = extract_images_from_page(doc, doc[0], 1, tmp_path / "img")
    assert len(kept.images) == 1, "the genuinely drawn instance is kept"
    doc.close()


def test_extracted_image_carries_content_digest(tmp_path: Path):
    """The digest keys the description cache, so identical embedded images share
    one description regardless of page or xref (T-054)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(72, 72, 172, 172), pixmap=_pix())
    result = extract_images_from_page(doc, page, 1, tmp_path / "img")
    doc.close()
    assert len(result.images) == 1
    digest = result.images[0].digest
    assert isinstance(digest, str) and len(digest) >= 12
