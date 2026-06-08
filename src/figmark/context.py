"""Grab N words of text context immediately before and after an image/diagram.

Used to give the description model domain context — without it a diagram is
interpreted purely visually; with a few words of surrounding text the model
learns what the report is about.

Pulls text from the same page first, then continues to the previous/next page
if the word quota is not yet filled. Skips other image/diagram blocks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContextText:
    before: str
    after: str

    def is_empty(self) -> bool:
        return not self.before.strip() and not self.after.strip()

    def format_for_prompt(self) -> str:
        """Format the context for insertion into the description prompt."""
        parts: list[str] = []
        if self.before.strip():
            parts.append(f"[Text context before the image]\n{self.before.strip()}")
        if self.after.strip():
            parts.append(f"[Text context after the image]\n{self.after.strip()}")
        return "\n\n".join(parts)


def _text_above(page, y_top: float) -> str:
    """Join text blocks on a page that lie entirely above y_top."""
    # Import here to avoid a circular import.
    from .pdf_loader import TextBlock

    parts = []
    for block in page.blocks:
        if not isinstance(block, TextBlock):
            continue
        if block.bbox[3] <= y_top:
            parts.append(block.text)
    return " ".join(parts)


def _text_below(page, y_bottom: float) -> str:
    """Join text blocks on a page that lie entirely below y_bottom."""
    from .pdf_loader import TextBlock

    parts = []
    for block in page.blocks:
        if not isinstance(block, TextBlock):
            continue
        if block.bbox[1] >= y_bottom:
            parts.append(block.text)
    return " ".join(parts)


def _all_page_text(page) -> str:
    from .pdf_loader import TextBlock

    return " ".join(b.text for b in page.blocks if isinstance(b, TextBlock))


def get_text_context_around(
    pages,
    page_num: int,
    bbox: tuple[float, float, float, float],
    words_before: int,
    words_after: int,
) -> ContextText:
    """Return N words of text immediately before and after bbox in reading order.

    Pulls from the same page first (above/below bbox), then from the previous/next
    pages if the word quota is not yet filled.
    """
    # Find the page index.
    page_idx = None
    for i, p in enumerate(pages):
        if p.page_num == page_num:
            page_idx = i
            break
    if page_idx is None:
        return ContextText(before="", after="")

    current_page = pages[page_idx]

    # ============ Before: start on the same page, walk backwards as needed ============
    before_chunks: list[str] = []  # ordered with the nearest-to-image chunk last
    remaining = words_before

    if remaining > 0:
        same_above = _text_above(current_page, bbox[1])
        words = same_above.split()
        if words:
            take = words[-remaining:]
            before_chunks.insert(0, " ".join(take))
            remaining -= len(take)

        prev_idx = page_idx - 1
        while remaining > 0 and prev_idx >= 0:
            prev_text = _all_page_text(pages[prev_idx])
            words = prev_text.split()
            if words:
                take = words[-remaining:]
                before_chunks.insert(0, " ".join(take))
                remaining -= len(take)
            prev_idx -= 1

    # ============ After: start on the same page, walk forwards as needed ============
    after_chunks: list[str] = []  # ordered in reading order
    remaining = words_after

    if remaining > 0:
        same_below = _text_below(current_page, bbox[3])
        words = same_below.split()
        if words:
            take = words[:remaining]
            after_chunks.append(" ".join(take))
            remaining -= len(take)

        next_idx = page_idx + 1
        while remaining > 0 and next_idx < len(pages):
            next_text = _all_page_text(pages[next_idx])
            words = next_text.split()
            if words:
                take = words[:remaining]
                after_chunks.append(" ".join(take))
                remaining -= len(take)
            next_idx += 1

    return ContextText(
        before=" ".join(before_chunks).strip(),
        after=" ".join(after_chunks).strip(),
    )
