"""Tester för annotate-modulen — mot verkliga PDF:er.

Live-tester för full pipeline + annotate finns i test_pipeline.py
(`test_pipeline_annotate_pdf_produces_annotated_copy`). Här testar vi
annotate-modulen isolerat med riktiga PDF:er som källa.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from src.annotate import AnnotationItem, annotate_pdf


def test_annotate_creates_output_file(pentland_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    items = [
        AnnotationItem(page_num=1, bbox=(100, 200, 300, 400), text="En testbild.", kind="Bild"),
    ]
    annotate_pdf(pentland_pdf, target, items)
    assert target.exists()
    assert target.stat().st_size > 0


def test_annotate_does_not_modify_source(pentland_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    original_bytes = pentland_pdf.read_bytes()
    items = [AnnotationItem(page_num=1, bbox=(10, 10, 100, 100), text="x", kind="Bild")]
    annotate_pdf(pentland_pdf, target, items)
    assert pentland_pdf.read_bytes() == original_bytes


def test_annotate_one_per_item_across_real_pdf(pentland_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    items = [
        AnnotationItem(page_num=1, bbox=(50, 50, 200, 200), text="A", kind="Bild"),
        AnnotationItem(page_num=1, bbox=(300, 300, 400, 400), text="B", kind="Diagram"),
        AnnotationItem(page_num=5, bbox=(50, 50, 150, 150), text="C", kind="Bild"),
        AnnotationItem(page_num=16, bbox=(50, 50, 150, 150), text="D", kind="Bild"),
    ]
    annotate_pdf(pentland_pdf, target, items)

    doc = fitz.open(target)
    try:
        total = sum(len(list(p.annots())) for p in doc)
        assert total == 4
    finally:
        doc.close()


def test_annotation_text_matches_syntolkning_in_real_pdf(
    pentland_pdf: Path, tmp_path: Path
):
    target = tmp_path / "annotated.pdf"
    syntolkning = (
        "Här syns ett diagram över KPIF-prognoser från 2025 till 2029. "
        "Tre scenarier visas: huvudscenario, högre och lägre inflation."
    )
    items = [
        AnnotationItem(page_num=1, bbox=(100, 200, 300, 400), text=syntolkning, kind="Diagram"),
    ]
    annotate_pdf(pentland_pdf, target, items)

    doc = fitz.open(target)
    try:
        page1 = doc.load_page(0)
        contents = [a.info.get("content") for a in page1.annots()]
        assert syntolkning in contents
    finally:
        doc.close()


def test_annotation_kind_in_title(pentland_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    items = [
        AnnotationItem(page_num=1, bbox=(10, 10, 100, 100), text="x", kind="Bild"),
        AnnotationItem(page_num=2, bbox=(10, 10, 100, 100), text="y", kind="Diagram"),
    ]
    annotate_pdf(pentland_pdf, target, items)

    doc = fitz.open(target)
    try:
        page1 = doc.load_page(0)
        page2 = doc.load_page(1)
        bild_titles = [a.info.get("title", "") for a in page1.annots()]
        diagram_titles = [a.info.get("title", "") for a in page2.annots()]
        assert any("Bild" in t for t in bild_titles)
        assert any("Diagram" in t for t in diagram_titles)
    finally:
        doc.close()


def test_annotated_real_pdf_remains_parseable(pentland_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    items = [
        AnnotationItem(page_num=1, bbox=(10, 10, 100, 100), text="x", kind="Bild"),
        AnnotationItem(page_num=8, bbox=(10, 10, 100, 100), text="y", kind="Diagram"),
    ]
    annotate_pdf(pentland_pdf, target, items)
    doc = fitz.open(target)
    try:
        for page in doc:
            _ = page.get_text("text")
            list(page.annots())
        assert len(doc) == 16  # Pentland är 16 sidor
    finally:
        doc.close()


def test_annotate_empty_items_produces_clean_copy(pentland_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    annotate_pdf(pentland_pdf, target, [])
    doc = fitz.open(target)
    try:
        assert len(doc) == 16
        for p in doc:
            assert len(list(p.annots())) == 0
    finally:
        doc.close()


def test_annotate_invalid_page_num_fails_loudly(pentland_pdf: Path, tmp_path: Path):
    target = tmp_path / "annotated.pdf"
    items = [AnnotationItem(page_num=99, bbox=(10, 10, 100, 100), text="x", kind="Bild")]
    with pytest.raises(ValueError, match="page_num=99"):
        annotate_pdf(pentland_pdf, target, items)
