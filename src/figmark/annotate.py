"""Write figure descriptions as text annotations into a copy of the PDF.

PyMuPDF's text annotation (`page.add_text_annot`) creates a "sticky note" icon at
a given position. The content shows on hover/click in PDF readers, and most
screen readers (NVDA, JAWS) pick up the /Contents field.

This is MVP accessibility. For real PDF/UA tagging, see docs/tickets/T-004.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class AnnotationItem:
    """A description to embed as an annotation in a PDF."""

    page_num: int  # 1-indexed
    bbox: tuple[float, float, float, float]  # image position in PDF coords
    text: str  # the description itself
    kind: str  # "Image" or "Diagram"


def annotate_pdf(
    source_pdf: Path,
    target_pdf: Path,
    items: list[AnnotationItem],
) -> None:
    """Create a copy of source_pdf with a text annotation for each item.

    The source file is left untouched. If items is empty, target is a plain copy.
    Fails loudly if an item's page_num falls outside the PDF's pages.
    """
    doc = fitz.open(source_pdf)
    try:
        n_pages = len(doc)
        # Validate ALL items before we start writing — otherwise a bad item could
        # leave us with a half-finished output.
        for item in items:
            if item.page_num < 1 or item.page_num > n_pages:
                raise ValueError(
                    f"AnnotationItem page_num={item.page_num} is outside "
                    f"the PDF's pages (1..{n_pages})"
                )

        for item in items:
            page = doc.load_page(item.page_num - 1)
            point = fitz.Point(item.bbox[0], item.bbox[1])
            annot = page.add_text_annot(point, item.text)
            # Set the title via the dict API (keyword args crash in PyMuPDF 1.27).
            info = annot.info
            info["title"] = f"Description of {item.kind}"
            info["content"] = item.text
            annot.set_info(info)

        target_pdf.parent.mkdir(parents=True, exist_ok=True)
        # garbage=4 + clean=True tidies the object graph so consumers on an
        # old/strict PyMuPDF do not crash on inconsistent annotation references.
        doc.save(target_pdf, garbage=4, clean=True, deflate=True)
    finally:
        doc.close()
