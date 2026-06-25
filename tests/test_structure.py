"""Tests for typography-based structure inference (headings, lists) — T-042."""

from __future__ import annotations

from figmark.output import PageData, to_markdown
from figmark.pdf_loader import TextBlock
from figmark.structure import as_list_item, body_font_size


def _page(blocks: list) -> PageData:
    return PageData(page_num=1, is_ocr=False, blocks=blocks)


def test_body_font_size_is_the_dominant_size():
    blocks = [
        TextBlock((0, 0, 500, 12), "body text " * 30, size=10.0),
        TextBlock((0, 0, 200, 16), "Heading", size=14.0, bold=True),
    ]
    assert body_font_size([_page(blocks)]) == 10.0


def test_headings_rendered_with_levels_by_size():
    blocks = [
        TextBlock((50, 40, 500, 60), "Big Title", size=18.0, bold=True),
        TextBlock((50, 70, 500, 84), "1 Introduction", size=13.0, bold=True),
        TextBlock((50, 90, 500, 300), "Ordinary body paragraph. " * 40, size=10.0),
    ]
    md = to_markdown([_page(blocks)])
    assert "# Big Title" in md  # largest size → H1
    assert "## 1 Introduction" in md  # next size → H2
    assert "# Ordinary body paragraph." not in md  # body is not a heading


def test_bold_at_body_size_is_a_deeper_heading():
    blocks = [
        TextBlock((50, 40, 500, 56), "2 Section", size=13.0, bold=True),
        TextBlock((50, 60, 500, 74), "2.1 Subsection", size=10.0, bold=True),
        TextBlock((50, 80, 500, 300), "Body text here. " * 40, size=10.0),
    ]
    md = to_markdown([_page(blocks)])
    # Only one size sits above body here, so it is H1; bold-at-body is one level
    # deeper (H2) — the point is the relative ordering, not absolute levels.
    assert "# 2 Section" in md
    assert "## 2.1 Subsection" in md


def test_vertical_margin_text_is_not_a_heading():
    """A large-but-rotated margin block (e.g. an arXiv stamp) must not become a
    heading — the horizontal gate rejects tall, narrow blocks."""
    blocks = [
        TextBlock((10, 40, 25, 400), "arXiv:1505.04597 18 May 2015", size=20.0),
        TextBlock((50, 40, 500, 300), "Body paragraph text. " * 40, size=10.0),
    ]
    md = to_markdown([_page(blocks)])
    assert not any(line.startswith("#") for line in md.splitlines())


def test_as_list_item():
    assert as_list_item("• first point") == "- first point"
    assert as_list_item("– dashed point") == "- dashed point"
    assert as_list_item("- already a dash") == "- already a dash"
    assert as_list_item("Normal paragraph text") is None
