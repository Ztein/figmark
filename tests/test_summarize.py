"""Unit tests for document-summary sample collection (offline, no API)."""

from __future__ import annotations

from figmark.output import PageData
from figmark.pdf_loader import ImageBlock, TextBlock
from figmark.summarize import collect_sample_text


def _text_page(page_num: int, text: str) -> PageData:
    page = PageData(page_num=page_num, is_ocr=False)
    page.blocks = [TextBlock(bbox=(0, 0, 100, 20), text=text)]
    return page


def test_collect_sample_text_caps_at_max_words():
    pages = [_text_page(1, "one two three four five"), _text_page(2, "six seven eight")]
    assert collect_sample_text(pages, max_words=4) == "one two three four"


def test_collect_sample_text_spans_pages_until_quota():
    pages = [_text_page(1, "a b"), _text_page(2, "c d e")]
    assert collect_sample_text(pages, max_words=4) == "a b c d"


def test_collect_sample_text_reads_ocr_pages():
    page = PageData(page_num=1, is_ocr=True)
    page.ocr_text = "scanned words here"
    assert collect_sample_text([page], max_words=2) == "scanned words"


def test_collect_sample_text_ignores_image_blocks():
    page = PageData(page_num=1, is_ocr=False)
    page.blocks = [
        ImageBlock(bbox=(0, 0, 10, 10), xref=1),
        TextBlock(bbox=(0, 20, 100, 40), text="real text"),
    ]
    assert collect_sample_text([page], max_words=10) == "real text"


def test_collect_sample_text_empty_when_no_text():
    page = PageData(page_num=1, is_ocr=False)
    assert collect_sample_text([page], max_words=10) == ""
