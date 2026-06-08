"""Tests for the annotate module — against real PDFs.

Live tests for the full pipeline + annotate live in test_pipeline.py
(`test_pipeline_annotate_pdf_produces_annotated_copy`). Here we test the annotate
module in isolation with a real PDF as the source.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from figmark.annotate import AnnotationItem, annotate_pdf


def _page_count(pdf_path: Path) -> int:
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def test_annotate_creates_output_file(paper_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    items = [
        AnnotationItem(page_num=1, bbox=(100, 200, 300, 400), text="A test image.", kind="Image"),
    ]
    annotate_pdf(paper_pdf, target, items)
    assert target.exists()
    assert target.stat().st_size > 0


def test_annotate_does_not_modify_source(paper_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    original_bytes = paper_pdf.read_bytes()
    items = [AnnotationItem(page_num=1, bbox=(10, 10, 100, 100), text="x", kind="Image")]
    annotate_pdf(paper_pdf, target, items)
    assert paper_pdf.read_bytes() == original_bytes


def test_annotate_one_per_item_across_real_pdf(paper_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    n = _page_count(paper_pdf)
    pages = sorted({1, max(1, n // 2), n})  # valid pages spread across the document
    items = [
        AnnotationItem(page_num=p, bbox=(50, 50, 200, 200), text=f"item-{p}", kind="Image")
        for p in pages
    ]
    annotate_pdf(paper_pdf, target, items)

    doc = fitz.open(target)
    try:
        total = sum(len(list(p.annots())) for p in doc)
        assert total == len(items)
    finally:
        doc.close()


def test_annotation_text_matches_description_in_real_pdf(paper_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    description = (
        "The figure shows a diagram of CPIF forecasts from 2025 to 2029. "
        "Three scenarios are shown: a main scenario, higher and lower inflation."
    )
    items = [
        AnnotationItem(page_num=1, bbox=(100, 200, 300, 400), text=description, kind="Diagram"),
    ]
    annotate_pdf(paper_pdf, target, items)

    doc = fitz.open(target)
    try:
        page1 = doc.load_page(0)
        contents = [a.info.get("content") for a in page1.annots()]
        assert description in contents
    finally:
        doc.close()


def test_annotation_kind_in_title(paper_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    items = [
        AnnotationItem(page_num=1, bbox=(10, 10, 100, 100), text="x", kind="Image"),
        AnnotationItem(page_num=1, bbox=(120, 120, 200, 200), text="y", kind="Diagram"),
    ]
    annotate_pdf(paper_pdf, target, items)

    doc = fitz.open(target)
    try:
        titles = [a.info.get("title", "") for a in doc.load_page(0).annots()]
        assert any("Image" in t for t in titles)
        assert any("Diagram" in t for t in titles)
    finally:
        doc.close()


def test_annotated_real_pdf_remains_parseable(paper_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    n = _page_count(paper_pdf)
    items = [AnnotationItem(page_num=1, bbox=(10, 10, 100, 100), text="x", kind="Image")]
    annotate_pdf(paper_pdf, target, items)
    doc = fitz.open(target)
    try:
        for page in doc:
            _ = page.get_text("text")
            list(page.annots())
        assert len(doc) == n
    finally:
        doc.close()


def test_annotate_empty_items_produces_clean_copy(paper_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    annotate_pdf(paper_pdf, target, [])
    doc = fitz.open(target)
    try:
        assert len(doc) >= 1
        for p in doc:
            assert len(list(p.annots())) == 0
    finally:
        doc.close()


def test_annotate_invalid_page_num_fails_loudly(paper_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    items = [AnnotationItem(page_num=10000, bbox=(10, 10, 100, 100), text="x", kind="Image")]
    with pytest.raises(ValueError, match="page_num=10000"):
        annotate_pdf(paper_pdf, target, items)
