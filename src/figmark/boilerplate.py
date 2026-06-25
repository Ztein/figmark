"""Strip running headers/footers and page numbers from the body text. (T-043)

These repeat on every page and leak into the Markdown/raw text as noise. A block is
dropped only when it sits in the top/bottom margin AND either its text recurs on a
large share of pages (a running header/footer) or it is shaped like a page number.
Requiring both repetition/shape *and* margin position keeps real content safe.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .pdf_loader import TextBlock

MARGIN_BAND = 0.12  # top/bottom fraction of the page treated as margin
MIN_PAGES = 4  # too few pages to trust repetition below this
REPEAT_FRACTION = 0.5  # a header/footer must recur on at least this share of pages

# "12", "Page 12", "12 / 30", "12 of 30" (optionally wrapped in dashes).
_PAGE_NUMBER = re.compile(r"^(page\s+)?\d{1,4}(\s*/\s*\d{1,4}|\s+of\s+\d{1,4})?$", re.IGNORECASE)


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def _in_margin(block: TextBlock, height: float) -> bool:
    if height <= 0:
        return False
    return block.bbox[1] < MARGIN_BAND * height or block.bbox[3] > (1 - MARGIN_BAND) * height


def _is_page_number(text: str) -> bool:
    return bool(_PAGE_NUMBER.match(text.strip().strip("-–—").strip()))


def strip_boilerplate(pages) -> int:
    """Remove running headers/footers and page numbers in place; return the count.

    No-op for short documents (repetition isn't trustworthy) and OCR pages (no
    blocks). Only margin TextBlocks are eligible.
    """
    text_pages = [p for p in pages if not p.is_ocr]
    n = len(text_pages)
    if n < MIN_PAGES:
        return 0

    occ: dict[str, set[int]] = defaultdict(set)
    margin: list[tuple[object, TextBlock, str]] = []
    for pi, page in enumerate(text_pages):
        for b in page.blocks:
            if isinstance(b, TextBlock) and _in_margin(b, page.page_height):
                key = _norm(b.text)
                occ[key].add(pi)
                margin.append((page, b, key))

    repeat_threshold = max(3, round(REPEAT_FRACTION * n))
    drop_ids = {
        id(b)
        for _page, b, key in margin
        if len(occ[key]) >= repeat_threshold or _is_page_number(b.text)
    }
    if not drop_ids:
        return 0

    removed = 0
    for page in text_pages:
        before = len(page.blocks)
        page.blocks = [b for b in page.blocks if id(b) not in drop_ids]
        removed += before - len(page.blocks)
    return removed
