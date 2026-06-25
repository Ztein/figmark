"""Tests for running header/footer + page-number stripping (T-043)."""

from __future__ import annotations

from figmark.boilerplate import strip_boilerplate
from figmark.output import PageData
from figmark.pdf_loader import TextBlock


def _page(num: int, blocks: list) -> PageData:
    return PageData(page_num=num, is_ocr=False, page_height=800.0, blocks=blocks)


def _doc(n_pages: int) -> list[PageData]:
    pages = []
    for i in range(1, n_pages + 1):
        pages.append(
            _page(
                i,
                [
                    TextBlock((50, 20, 500, 35), "Monetary Policy Report", size=9.0),  # header
                    TextBlock((50, 120, 500, 400), f"Body content of page {i}. " * 8, size=10.0),
                    TextBlock((280, 772, 320, 786), str(i), size=9.0),  # page number (footer)
                ],
            )
        )
    return pages


def test_strips_running_header_and_page_numbers():
    pages = _doc(6)
    removed = strip_boilerplate(pages)
    assert removed == 12  # 6 headers + 6 page numbers
    for p in pages:
        texts = [b.text for b in p.blocks]
        assert any("Body content" in t for t in texts), "body text must survive"
        assert all("Monetary Policy Report" not in t for t in texts), "header must go"
        assert str(p.page_num) not in texts, "page number must go"


def test_noop_for_short_document():
    """Too few pages to trust repetition → nothing is dropped."""
    pages = _doc(3)
    assert strip_boilerplate(pages) == 0
    for p in pages:
        assert any("Monetary Policy Report" in b.text for b in p.blocks)


def test_body_text_in_the_margin_band_is_kept_if_not_repeated():
    """A one-off line that happens to sit in the margin must not be dropped."""
    pages = _doc(6)
    pages[2].blocks.append(TextBlock((50, 25, 500, 40), "A unique top-of-page note", size=10.0))
    strip_boilerplate(pages)
    survivors = [b.text for b in pages[2].blocks]
    assert any("unique top-of-page note" in t for t in survivors)
