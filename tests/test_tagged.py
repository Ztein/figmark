"""Tests for PDF/UA structure-tree tagging (T-004, offline).

Validates the structure tree the foundation builds: a StructTreeRoot with a
Figure element per item carrying /Alt, plus /MarkInfo and /Lang. (Full PDF/UA
conformance is out of scope here — see the ticket.)
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from figmark.annotate import AnnotationItem
from figmark.tagged import lang_code, tag_pdf

from .fakes import synthetic_pdf


def test_lang_code_maps_known_names_and_skips_unknown():
    assert lang_code("Swedish") == "sv"
    assert lang_code("english") == "en"
    assert lang_code("Klingon") is None
    assert lang_code(None) is None
    assert lang_code("") is None


def _items() -> list[AnnotationItem]:
    return [
        AnnotationItem(page_num=1, bbox=(72, 200, 172, 300), text="A blue square.", kind="Image"),
        AnnotationItem(page_num=1, bbox=(72, 320, 200, 360), text="A line chart.", kind="Diagram"),
    ]


def test_tag_pdf_builds_figure_structure_tree(tmp_path: Path):
    src = synthetic_pdf(tmp_path / "doc.pdf")
    out = tmp_path / "doc_tagged.pdf"

    tag_pdf(src, out, _items(), lang="sv")

    assert out.exists()
    with pikepdf.open(out) as pdf:
        root = pdf.Root
        assert bool(root.MarkInfo.Marked) is True
        assert str(root.Lang) == "sv"

        struct_root = root.StructTreeRoot
        assert str(struct_root.Type) == "/StructTreeRoot"
        doc_elem = struct_root.K[0]
        assert str(doc_elem.S) == "/Document"

        figures = doc_elem.K
        assert len(figures) == 2
        alts = {str(f.Alt) for f in figures}
        assert alts == {"A blue square.", "A line chart."}
        for f in figures:
            assert str(f.S) == "/Figure"
            assert f.Pg is not None  # anchored to a page


def test_tag_pdf_without_lang_omits_lang(tmp_path: Path):
    src = synthetic_pdf(tmp_path / "doc.pdf")
    out = tmp_path / "doc_tagged.pdf"
    tag_pdf(src, out, _items(), lang=None)
    with pikepdf.open(out) as pdf:
        assert "/Lang" not in pdf.Root


def test_tag_pdf_rejects_out_of_range_page(tmp_path: Path):
    src = synthetic_pdf(tmp_path / "doc.pdf")
    out = tmp_path / "doc_tagged.pdf"
    bad = [AnnotationItem(page_num=99, bbox=(0, 0, 1, 1), text="x", kind="Image")]
    with pytest.raises(ValueError, match="outside"):
        tag_pdf(src, out, bad, lang=None)
    assert not out.exists()  # nothing written on a validation failure
