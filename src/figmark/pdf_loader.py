"""Open a PDF and turn each page into ordered blocks.

Yields text and image blocks in reading order (sorted by y, then x), and
classifies whether the document is scanned — average characters per page below a
threshold means the OCR pipeline takes over instead of direct text extraction.
"""

from __future__ import annotations

import unicodedata
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


# Per-page OCR decision (T-027). A page is treated as scanned only when it has
# little extractable text AND a near-full-page image covering it — i.e. the text
# really is locked inside a raster. A genuinely sparse page (section divider,
# figure-only, blank) also has little text but no full-page image, so it stays on
# the text path and is not needlessly OCR'd.
PAGE_OCR_MIN_CHARS = 50
PAGE_OCR_IMAGE_COVERAGE = 0.5


def page_image_coverage(page: fitz.Page) -> float:
    """Largest fraction of the page area covered by a single image (0..1)."""
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    best = 0.0
    for info in page.get_image_info(xrefs=True):
        rect = fitz.Rect(info.get("bbox", (0, 0, 0, 0)))
        area = abs(rect.width * rect.height)
        if area > best:
            best = area
    return min(best / page_area, 1.0)


def page_needs_ocr(page: fitz.Page) -> tuple[bool, str]:
    """Decide per page whether to OCR rather than extract text. Returns (ocr, reason).

    Scanned page = little extractable text AND a near-full-page image. A page with
    little text but no large image is sparse-but-digital and stays on the text path.
    """
    chars = len(page.get_text("text").strip())
    if chars >= PAGE_OCR_MIN_CHARS:
        return False, f"{chars} chars (text-encoded)"
    coverage = page_image_coverage(page)
    if coverage >= PAGE_OCR_IMAGE_COVERAGE:
        return True, f"{chars} chars + image covers {coverage:.0%} of the page (scanned)"
    return False, f"{chars} chars, no full-page image (sparse, not scanned)"


# A text layer with more than this fraction of mojibake characters is flagged as
# likely broken (T-028). Conservative, since it only warns — it does not change
# behaviour, so a false positive costs a log line, not a needless OCR pass.
GARBLE_WARN_RATIO = 0.10


def text_garble_ratio(text: str) -> float:
    """Fraction of characters that signal a broken text layer (mojibake), 0..1.

    Counts Private Use Area glyphs (a missing/broken ToUnicode CMap dumps glyphs
    there), the U+FFFD replacement character, and control characters other than
    normal whitespace. Clean text scores 0.0.
    """
    if not text:
        return 0.0
    bad = 0
    for ch in text:
        if 0xE000 <= ord(ch) <= 0xF8FF or ch == "�":
            bad += 1
        elif ch not in "\n\r\t" and unicodedata.category(ch)[0] == "C":
            bad += 1
    return bad / len(text)


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
