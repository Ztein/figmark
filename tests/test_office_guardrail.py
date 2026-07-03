"""T-056: the spreadsheet page-explosion guardrail is loud, not silent.

A spreadsheet with no intrinsic page count can paginate into hundreds of PDF
pages of flattened numbers. We can't reconstruct the table without a
spreadsheet-native extractor (deferred), but the explosion must never be
silent. These tests exercise the guardrail directly with synthetic PDFs — no
LibreOffice needed, so they run in the offline suite.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz

from figmark.office import (
    SPREADSHEET_PAGE_WARN_THRESHOLD,
    _warn_on_spreadsheet_page_explosion,
)


def _pdf_with_pages(path: Path, n: int) -> Path:
    doc = fitz.open()
    for _ in range(n):
        doc.new_page()
    doc.save(path)
    doc.close()
    return path


def test_large_spreadsheet_pdf_warns_loudly(tmp_path: Path, caplog):
    pdf = _pdf_with_pages(tmp_path / "big.pdf", SPREADSHEET_PAGE_WARN_THRESHOLD + 10)
    with caplog.at_level(logging.WARNING, logger="figmark.office"):
        _warn_on_spreadsheet_page_explosion(tmp_path / "riksbank-fx.xlsx", pdf)
    assert "SPREADSHEET PAGE EXPLOSION" in caplog.text
    assert "riksbank-fx.xlsx" in caplog.text
    assert str(SPREADSHEET_PAGE_WARN_THRESHOLD + 10) in caplog.text


def test_small_spreadsheet_pdf_is_quiet(tmp_path: Path, caplog):
    pdf = _pdf_with_pages(tmp_path / "small.pdf", 3)
    with caplog.at_level(logging.WARNING, logger="figmark.office"):
        _warn_on_spreadsheet_page_explosion(tmp_path / "tiny.xlsx", pdf)
    assert "EXPLOSION" not in caplog.text


def test_non_spreadsheet_never_warns(tmp_path: Path, caplog):
    """A long docx/pptx is legitimately many pages — the warning is for
    spreadsheets, whose page count is a pagination artefact, not content."""
    pdf = _pdf_with_pages(tmp_path / "report.pdf", SPREADSHEET_PAGE_WARN_THRESHOLD + 50)
    with caplog.at_level(logging.WARNING, logger="figmark.office"):
        _warn_on_spreadsheet_page_explosion(tmp_path / "annual-report.docx", pdf)
    assert "EXPLOSION" not in caplog.text
