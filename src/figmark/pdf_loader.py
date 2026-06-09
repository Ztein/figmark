"""Open a PDF and turn each page into ordered blocks.

Yields text and image blocks in reading order (sorted by y, then x), and
classifies whether the document is scanned — average characters per page below a
threshold means the OCR pipeline takes over instead of direct text extraction.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class TextBlock:
    bbox: tuple[float, float, float, float]
    text: str
    kind: str = "text"


@dataclass
class ImageBlock:
    bbox: tuple[float, float, float, float]
    xref: int
    kind: str = "image"


@dataclass
class DiagramBlock:
    bbox: tuple[float, float, float, float]
    region_index: int  # matches DiagramRegion.index within a page
    kind: str = "diagram"


Block = TextBlock | ImageBlock | DiagramBlock

# Technical threshold — if a PDF averages fewer characters per page than this,
# the whole document is classified as scanned and the OCR pipeline kicks in.
SCANNED_MIN_AVG_CHARS_PER_PAGE = 50


def open_pdf(path: str | Path) -> fitz.Document:
    doc = fitz.open(path)
    if doc.needs_pass:
        doc.close()
        raise RuntimeError("Password-protected PDFs are not supported.")
    return doc


def is_scanned(doc: fitz.Document) -> bool:
    if len(doc) == 0:
        return False
    total = sum(len(page.get_text("text").strip()) for page in doc)
    avg = total / len(doc)
    return avg < SCANNED_MIN_AVG_CHARS_PER_PAGE


def iter_page_blocks(page: fitz.Page) -> list[Block]:
    """Return the page's text and image blocks in reading order (y, x).

    Text blocks come from page.get_text("dict") (type 0). Image blocks are built
    from page.get_image_info(xrefs=True) rather than the dict output's type 1 —
    the dict output reports a block number in the "number" field, not the actual
    xref needed to match against page.get_images() and doc.extract_image().
    """
    blocks: list[Block] = []

    raw = page.get_text("dict")
    for b in raw.get("blocks", []):
        if b.get("type") != 0:
            continue
        bbox = tuple(b.get("bbox", (0.0, 0.0, 0.0, 0.0)))
        text = _join_text_block(b)
        if text.strip():
            blocks.append(TextBlock(bbox=bbox, text=text))

    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref", 0)
        if not xref:
            continue
        bbox = tuple(info.get("bbox", (0.0, 0.0, 0.0, 0.0)))
        blocks.append(ImageBlock(bbox=bbox, xref=int(xref)))

    blocks.sort(key=lambda blk: (round(blk.bbox[1] / 10), blk.bbox[0]))
    return blocks


def _join_text_block(block: dict) -> str:
    lines = []
    for line in block.get("lines", []):
        spans = [span.get("text", "") for span in line.get("spans", [])]
        joined = "".join(spans)
        if joined:
            lines.append(joined)
    return "\n".join(lines)


def iter_pages(doc: fitz.Document) -> Iterator[tuple[int, fitz.Page]]:
    yield from enumerate(doc, start=1)
