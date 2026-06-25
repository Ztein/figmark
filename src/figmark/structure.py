"""Infer document structure (headings, lists) from typography. (T-042)

The PDF gives no semantic tags, so headings are inferred from font size/weight:
the dominant body size is the most common one across the document, and short
horizontal blocks that are larger than body (or bold at body size) are headings,
ranked into Markdown levels by size. "Horizontal" rejects rotated margin text such
as an arXiv stamp. This is a good-enough outline, not a perfect one.
"""

from __future__ import annotations

import re
from collections import Counter

from .pdf_loader import TextBlock

MAX_HEADING_WORDS = 18  # headings are short
MAX_HEADING_LINES = 3
MAX_HEADING_LEVEL = 6  # Markdown caps at H6

# A leading bullet glyph (incl. an ASCII hyphen/asterisk used as a bullet).
_BULLET = re.compile(r"^\s*[•▪◦‣·–\-*]\s+")


def body_font_size(pages) -> float:
    """The most common text size across the document, weighted by character count."""
    weights: Counter = Counter()
    for page in pages:
        for b in page.blocks:
            if isinstance(b, TextBlock) and b.size > 0:
                weights[b.size] += len(b.text)
    return weights.most_common(1)[0][0] if weights else 0.0


def _horizontal(block: TextBlock) -> bool:
    x0, y0, x1, y1 = block.bbox
    return (x1 - x0) >= (y1 - y0)  # rejects rotated/vertical margin text


def _is_heading_candidate(block, body: float) -> bool:
    if not isinstance(block, TextBlock) or body <= 0 or block.size <= 0:
        return False
    if len(block.text.split()) > MAX_HEADING_WORDS:
        return False
    if block.text.count("\n") + 1 > MAX_HEADING_LINES:
        return False
    if not _horizontal(block):
        return False
    return block.size > body or (block.bold and block.size >= body)


def heading_levels(pages, body: float) -> tuple[dict[float, int], int]:
    """Map each heading size to a Markdown level (1 = largest). Also returns the
    level used for bold-at-body-size headings (one below the smallest larger size).
    """
    sizes = sorted(
        {
            b.size
            for page in pages
            for b in page.blocks
            if _is_heading_candidate(b, body) and b.size > body
        },
        reverse=True,
    )
    size_level = {sz: min(i + 1, MAX_HEADING_LEVEL) for i, sz in enumerate(sizes)}
    bold_body_level = min(len(sizes) + 1, MAX_HEADING_LEVEL)
    return size_level, bold_body_level


def heading_level(block, body: float, size_level: dict[float, int], bold_body_level: int):
    """The Markdown heading level for a block, or None if it is not a heading."""
    if not _is_heading_candidate(block, body):
        return None
    if block.size > body:
        return size_level.get(block.size)
    return bold_body_level  # bold at body size


def as_list_item(text: str) -> str | None:
    """If a block reads as a bullet item, return it as a Markdown ``- `` item;
    numbered items already read as Markdown and are left to the caller. None if the
    block is not a bullet item.
    """
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    if not _BULLET.match(first):
        return None
    body = _BULLET.sub("", " ".join(text.split()), count=1)
    return f"- {body}"
