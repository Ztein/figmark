"""Per-page OCR decision with the image-coverage guard (T-027)."""

from __future__ import annotations

from pathlib import Path

import fitz

from figmark import pipeline as pipeline_module
from figmark.config import load_config
from figmark.ocr import OcrResult
from figmark.pdf_loader import open_pdf, page_image_coverage, page_needs_ocr

from .fakes import FakeClient


def _text_page(doc: fitz.Document) -> None:
    page = doc.new_page()
    page.insert_text((72, 72), "Real extractable body text about monetary policy. " * 8)


def _image_only_page(doc: fitz.Document) -> None:
    """A page that is one full-page image and no text — a scanned page."""
    page = doc.new_page()
    rect = page.rect
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, int(rect.width), int(rect.height)))
    pix.set_rect(pix.irect, (200, 200, 200))
    page.insert_image(rect, pixmap=pix)


def _sparse_page(doc: fitz.Document) -> None:
    """Little text, no full-page image — a divider, NOT a scanned page."""
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 3")


# --- unit: the classifier ------------------------------------------------


def test_text_page_is_not_ocr(tmp_path: Path):
    doc = fitz.open()
    _text_page(doc)
    needs, reason = page_needs_ocr(doc[0])
    assert needs is False
    assert "text-encoded" in reason


def test_full_page_image_without_text_is_ocr(tmp_path: Path):
    doc = fitz.open()
    _image_only_page(doc)
    assert page_image_coverage(doc[0]) >= 0.5
    needs, reason = page_needs_ocr(doc[0])
    assert needs is True
    assert "scanned" in reason


def test_sparse_page_is_not_ocr(tmp_path: Path):
    """The guard: little text but no big image → sparse, stays on the text path."""
    doc = fitz.open()
    _sparse_page(doc)
    needs, reason = page_needs_ocr(doc[0])
    assert needs is False
    assert "sparse" in reason


# --- integration: a scanned page inside a text PDF is rescued ------------


def test_mixed_document_ocrs_only_the_scanned_page(
    env_with_key, project_root: Path, tmp_path: Path, monkeypatch
):
    doc = fitz.open()
    _text_page(doc)  # page 1: digital text
    _image_only_page(doc)  # page 2: scanned
    _sparse_page(doc)  # page 3: sparse divider (must NOT be OCR'd)
    pdf = tmp_path / "mixed.pdf"
    doc.save(pdf)
    doc.close()

    # Avoid a real Tesseract dependency: the OCR'd page returns known text.
    # Long enough (and high-confidence) to NOT trigger the vision-OCR fallback,
    # so the Tesseract text is used as-is.
    scanned_text = "SCANNED PAGE BODY TEXT recovered by OCR, well past the char threshold."
    monkeypatch.setattr(
        pipeline_module,
        "ocr_page",
        lambda page, cfg: OcrResult(text=scanned_text, mean_confidence=99.0),
    )

    cfg = load_config(project_root / "config.example.yaml")
    result = pipeline_module.convert(
        pdf, cfg, tmp_path / "out", client=FakeClient("desc"), quiet=True
    )

    # The scanned page's text was rescued via OCR and appears in the output …
    assert "SCANNED PAGE BODY TEXT recovered by OCR" in result.markdown
    # … and the digital text page is still there.
    assert "monetary policy" in result.markdown


def test_classifier_matches_pipeline_decision_per_page(tmp_path: Path):
    doc = fitz.open()
    _text_page(doc)
    _image_only_page(doc)
    _sparse_page(doc)
    pdf = tmp_path / "mixed.pdf"
    doc.save(pdf)
    doc.close()

    opened = open_pdf(pdf)
    decisions = [page_needs_ocr(p)[0] for p in opened]
    assert decisions == [False, True, False]
