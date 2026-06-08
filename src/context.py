"""Plocka N ord text-kontext omedelbart före och efter en bild/diagram-position.

Används för att ge syntolkningsmodellen domänkontext — utan kontext tolkas
ett diagram bara visuellt; med några ord text ovan/under får modellen veta
vad rapporten handlar om.

Hämtar text från samma sida först, fortsätter till föregående/nästa sida om
ordkvoten inte är fylld. Hoppar över andra bild/diagram-block.
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
        """Formatera kontexten för insättning i syntolknings-prompten."""
        parts: list[str] = []
        if self.before.strip():
            parts.append(f"[Textsammanhang före bilden]\n{self.before.strip()}")
        if self.after.strip():
            parts.append(f"[Textsammanhang efter bilden]\n{self.after.strip()}")
        return "\n\n".join(parts)


def _text_above(page, y_top: float) -> str:
    """Sammanfoga text-block på en sida som ligger helt ovanför y_top."""
    # Importera här för att undvika cirkulär import
    from .pdf_loader import TextBlock
    parts = []
    for block in page.blocks:
        if not isinstance(block, TextBlock):
            continue
        if block.bbox[3] <= y_top:
            parts.append(block.text)
    return " ".join(parts)


def _text_below(page, y_bottom: float) -> str:
    """Sammanfoga text-block på en sida som ligger helt under y_bottom."""
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
    """Returnera N ord text omedelbart före och efter bbox i läsordning.

    Hämtar från samma sida först (ovan/under bbox), sen från föregående/nästa
    sidor om ordkvoten inte är fylld.
    """
    # Hitta sidans index
    page_idx = None
    for i, p in enumerate(pages):
        if p.page_num == page_num:
            page_idx = i
            break
    if page_idx is None:
        return ContextText(before="", after="")

    current_page = pages[page_idx]

    # ============ Före: börja på samma sida, gå bakåt vid behov ============
    before_chunks: list[str] = []  # ordnade närmst-bilden sist
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

    # ============ Efter: börja på samma sida, gå framåt vid behov ============
    after_chunks: list[str] = []  # ordnade i läsordning
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
