from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

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
    region_index: int  # matchar DiagramRegion.index per sida
    kind: str = "diagram"


Block = TextBlock | ImageBlock | DiagramBlock

# Teknisk tröskel — om en PDF har färre tecken per sida i snitt än så här
# klassificeras hela dokumentet som skannat och OCR-pipelinen aktiveras.
SCANNED_MIN_AVG_CHARS_PER_PAGE = 50


def open_pdf(path: str | Path) -> fitz.Document:
    doc = fitz.open(path)
    if doc.needs_pass:
        doc.close()
        raise RuntimeError("Lösenordsskyddade PDF:er stöds inte.")
    return doc


def is_scanned(doc: fitz.Document) -> bool:
    if len(doc) == 0:
        return False
    total = sum(len(page.get_text("text").strip()) for page in doc)
    avg = total / len(doc)
    return avg < SCANNED_MIN_AVG_CHARS_PER_PAGE


def iter_page_blocks(page: fitz.Page) -> list[Block]:
    """Returnera text- och bildblock på sidan i läsordning (y, x).

    Text-block kommer från page.get_text("dict") (typ 0). Image-block bygger vi
    från page.get_image_info(xrefs=True) istället för dict-outputens typ 1 —
    dict-outputen ger blocknummer i fältet "number", inte den faktiska xref:en
    som behövs för att matcha mot page.get_images() och doc.extract_image().
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
    for i, page in enumerate(doc, start=1):
        yield i, page
