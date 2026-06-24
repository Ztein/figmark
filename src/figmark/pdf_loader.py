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


@dataclass
class TableBlock:
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]  # row-major cell text; "" for an empty cell
    kind: str = "table"


Block = TextBlock | ImageBlock | DiagramBlock | TableBlock

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


# Reading order. A single global (y, x) sort interleaves columns on a multi-column
# page: a right-column block at the same y-band as left-column text sorts *between*
# the left blocks. We detect column boundaries from clustered block left-edges and,
# when the page is multi-column, order column-by-column (each top-to-bottom). A
# single-column page has no wide left-edge gap, so it falls back to the exact same
# (y, x) flow as before — no behaviour change for the common case. (T-036)
# A left-edge gap ≥ this fraction of the page width starts a new column.
COLUMN_GAP_RATIO = 0.06
# Each side of a candidate split must hold at least this many blocks.
MIN_BLOCKS_PER_COLUMN = 2


def _column_boundaries(blocks: list[Block], page_width: float) -> list[float]:
    """X positions that separate columns, inferred from clustered block left-edges.

    Empty for a single-column page (no left-edge gap wide enough), so callers fall
    back to the plain (y, x) flow.
    """
    if page_width <= 0 or len(blocks) < 2 * MIN_BLOCKS_PER_COLUMN:
        return []
    lefts = sorted(blk.bbox[0] for blk in blocks)
    min_gap = COLUMN_GAP_RATIO * page_width
    boundaries: list[float] = []
    for i in range(1, len(lefts)):
        if lefts[i] - lefts[i - 1] < min_gap:
            continue
        cut = (lefts[i - 1] + lefts[i]) / 2
        left_n = sum(1 for blk in blocks if blk.bbox[0] < cut)
        # Only a real column split — enough blocks on both sides (guards against a
        # lone centred title or indented line creating a spurious thin column).
        if MIN_BLOCKS_PER_COLUMN <= left_n <= len(blocks) - MIN_BLOCKS_PER_COLUMN:
            boundaries.append(cut)
    return boundaries


def _column_index(x0: float, boundaries: list[float]) -> int:
    return sum(1 for b in boundaries if x0 >= b)


def sort_blocks_reading_order(blocks: list[Block], page_width: float) -> list[Block]:
    """Sort blocks in place into reading order, column-aware. Returns the list."""
    boundaries = _column_boundaries(blocks, page_width)
    if not boundaries:
        blocks.sort(key=lambda blk: (round(blk.bbox[1] / 10), blk.bbox[0]))
    else:
        blocks.sort(
            key=lambda blk: (
                _column_index(blk.bbox[0], boundaries),
                round(blk.bbox[1] / 10),
                blk.bbox[0],
            )
        )
    return blocks


def iter_page_blocks(page: fitz.Page) -> list[Block]:
    """Return the page's text and image blocks in reading order (column-aware).

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

    return sort_blocks_reading_order(blocks, page.rect.width)


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
