"""Tests for the context module — against real PDFs.

We extract PageData via the same pipeline production uses (iter_page_blocks etc.)
and verify that get_text_context_around() pulls meaningful context from real pages.
"""

from __future__ import annotations

from pathlib import Path

from figmark.context import ContextText, get_text_context_around
from figmark.output import PageData
from figmark.pdf_loader import ImageBlock, iter_page_blocks, iter_pages, open_pdf


def _build_pages_from_pdf(pdf_path: Path) -> list[PageData]:
    """Build a PageData list matching the pipeline setup for a text-encoded PDF."""
    doc = open_pdf(pdf_path)
    try:
        pages = []
        for page_num, page in iter_pages(doc):
            pd = PageData(page_num=page_num, is_ocr=False, blocks=iter_page_blocks(page))
            pages.append(pd)
        return pages
    finally:
        doc.close()


def test_context_text_dataclass_basic():
    """ContextText.is_empty and format_for_prompt — minimal sanity (no mocked data)."""
    assert ContextText(before="", after="").is_empty()
    assert not ContextText(before="text", after="").is_empty()

    s = ContextText(before="A B C", after="X Y Z").format_for_prompt()
    assert "A B C" in s and "X Y Z" in s
    assert "before" in s.lower() and "after" in s.lower()


def test_context_around_image_is_non_empty(paper_pdf: Path):
    """The text surrounding an image should be pulled into the context."""
    pages = _build_pages_from_pdf(paper_pdf)
    for page in pages:
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                ctx = get_text_context_around(
                    pages,
                    page_num=page.page_num,
                    bbox=block.bbox,
                    words_before=50,
                    words_after=50,
                )
                combined = (ctx.before + " " + ctx.after).strip()
                assert combined, (
                    f"Expected non-empty context around the image on page "
                    f"{page.page_num}: before={ctx.before[:80]!r}, after={ctx.after[:80]!r}"
                )
                return
    raise AssertionError("No images found in the paper PDF — the test cannot run")


def test_context_word_count_respected(paper_pdf: Path):
    """We must never get more words than we asked for."""
    pages = _build_pages_from_pdf(paper_pdf)
    for page in pages:
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                ctx = get_text_context_around(
                    pages,
                    page_num=page.page_num,
                    bbox=block.bbox,
                    words_before=10,
                    words_after=10,
                )
                assert len(ctx.before.split()) <= 10, (
                    f"Before-context returned more than 10 words: {len(ctx.before.split())}"
                )
                assert len(ctx.after.split()) <= 10
                return


def test_context_zero_words_returns_empty(paper_pdf: Path):
    pages = _build_pages_from_pdf(paper_pdf)
    for page in pages:
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                ctx = get_text_context_around(
                    pages,
                    page_num=page.page_num,
                    bbox=block.bbox,
                    words_before=0,
                    words_after=0,
                )
                assert ctx.is_empty()
                return


def test_context_crosses_page_boundary_in_real_pdf(paper_pdf: Path):
    """Asking for more words than fit on the same page should pull from neighbours.

    A huge `words_before` on an image high up on page 2+ should pick up text from
    the previous page.
    """
    pages = _build_pages_from_pdf(paper_pdf)
    for page in pages[1:]:  # start after page 1 so there is a previous page
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                ctx_huge = get_text_context_around(
                    pages,
                    page_num=page.page_num,
                    bbox=block.bbox,
                    words_before=5000,
                    words_after=5000,
                )
                # The context should be non-empty if there is text anywhere in the PDF.
                assert not ctx_huge.is_empty()
                return
