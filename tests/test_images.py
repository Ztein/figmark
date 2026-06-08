from __future__ import annotations

from pathlib import Path

from figmark.images import extract_images_from_page
from figmark.pdf_loader import ImageBlock, iter_page_blocks, iter_pages, open_pdf


def test_extract_images_writes_files(paper_pdf: Path, tmp_path: Path):
    doc = open_pdf(paper_pdf)
    out_dir = tmp_path / "images"
    try:
        total_extracted = []
        for page_num, page in iter_pages(doc):
            extracted = extract_images_from_page(doc, page, page_num, out_dir)
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
            for img in extract_images_from_page(doc, page, page_num, out_dir):
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
        for page_num, page in iter_pages(doc):
            total.extend(extract_images_from_page(doc, page, page_num, out_dir))
        assert total == []
    finally:
        doc.close()
