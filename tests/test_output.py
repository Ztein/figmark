"""Unit tests for Markdown assembly (offline — synthetic PageData, no API)."""

from __future__ import annotations

from pathlib import Path

from figmark.images import ExtractedImage
from figmark.output import PageData, to_markdown
from figmark.pdf_loader import DiagramBlock, ImageBlock, TextBlock


def _text_page() -> PageData:
    img = ExtractedImage(
        path=Path("/tmp/out/images/page-001-img-01.png"),
        page_num=1,
        index=1,
        xref=42,
        bbox=(0, 100, 200, 300),
    )
    page = PageData(page_num=1, is_ocr=False)
    page.images = [img]
    page.blocks = [
        TextBlock(bbox=(0, 0, 200, 50), text="Intro paragraph."),
        ImageBlock(bbox=(0, 100, 200, 300), xref=42),
        DiagramBlock(bbox=(0, 320, 200, 500), region_index=1),
    ]
    page.descriptions = {42: "A photo of a cat."}
    page.diagram_descriptions = {1: "A line chart.\n\nIt rises over time."}
    return page


def test_markdown_embeds_text_image_and_diagram():
    md = to_markdown([_text_page()])

    assert "Intro paragraph." in md
    # One image embed and one diagram embed, in reading order.
    assert md.count("](images/") == 1
    assert md.count("](diagrams/") == 1
    assert "![Image, page 1](images/page-001-img-01.png)" in md
    assert "![Diagram, page 1](diagrams/page-001-diagram-01.png)" in md
    # Descriptions are rendered as blockquote captions.
    assert "> A photo of a cat." in md
    assert "> A line chart." in md
    # Reading order: text before image before diagram.
    assert md.index("Intro paragraph.") < md.index("images/") < md.index("diagrams/")


def test_markdown_skips_figures_without_descriptions():
    page = _text_page()
    page.descriptions = {}
    page.diagram_descriptions = {}
    md = to_markdown([page])

    assert "Intro paragraph." in md
    assert "](images/" not in md
    assert "](diagrams/" not in md


def test_markdown_ocr_page_emits_text_and_described_images():
    img = ExtractedImage(
        path=Path("/tmp/out/images/page-002-img-01.png"),
        page_num=2,
        index=1,
        xref=7,
        bbox=(0, 0, 100, 100),
    )
    page = PageData(page_num=2, is_ocr=True)
    page.ocr_text = "Scanned page text."
    page.images = [img]
    page.descriptions = {7: "A scanned figure."}

    md = to_markdown([page])
    assert "Scanned page text." in md
    assert md.count("](images/") == 1
    assert "> A scanned figure." in md
