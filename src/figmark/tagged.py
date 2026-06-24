"""Promote a PDF to a structure-tagged PDF for accessibility (T-004).

Builds a ``/StructTreeRoot`` with one ``/Figure`` element per described image or
diagram, each carrying the description as ``/Alt`` — the structure tree is what
PDF/UA-aware screen readers use, where a text annotation (T-005) is only a
complement. Also marks the document ``/MarkInfo /Marked true`` and sets a document
``/Lang``.

This is the structure-tree FOUNDATION, not full PDF/UA conformance. Full PDF/UA
additionally requires *all* page content to be tagged and each figure to be
MCID-anchored to marked content in the page stream (via a ``/ParentTree``); that,
plus validation with veraPDF/PAC and a screen reader, is follow-up work tracked in
docs/tickets/T-004. The source file is never modified — a new file is written.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from .annotate import AnnotationItem

# figmark works in language *names* (e.g. "Swedish"); the PDF /Lang entry wants a
# BCP-47 / ISO 639-1 code. Unknown languages → no /Lang (better than a wrong one).
_LANG_CODES = {
    "swedish": "sv",
    "english": "en",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "dutch": "nl",
    "portuguese": "pt",
}


def lang_code(language: str | None) -> str | None:
    """Map a detected language name to an ISO 639-1 code, or None if unknown."""
    if not language:
        return None
    return _LANG_CODES.get(language.strip().lower())


def tag_pdf(
    source_pdf: Path,
    target_pdf: Path,
    items: list[AnnotationItem],
    lang: str | None = None,
) -> None:
    """Write a copy of ``source_pdf`` to ``target_pdf`` with a Figure structure tree.

    Each item becomes a ``/Figure`` structure element with ``/Alt`` set to its
    description and ``/Pg`` pointing at its page. Fails loudly if an item's
    ``page_num`` is outside the document.
    """
    pdf = pikepdf.open(source_pdf)
    try:
        n_pages = len(pdf.pages)
        for item in items:
            if item.page_num < 1 or item.page_num > n_pages:
                raise ValueError(
                    f"AnnotationItem page_num={item.page_num} is outside "
                    f"the PDF's pages (1..{n_pages})"
                )

        root = pdf.Root
        root.MarkInfo = Dictionary(Marked=True)
        if lang:
            root.Lang = String(lang)

        struct_root = pdf.make_indirect(Dictionary(Type=Name.StructTreeRoot))
        doc_elem = pdf.make_indirect(
            Dictionary(Type=Name.StructElem, S=Name.Document, P=struct_root)
        )

        figures = Array()
        for item in items:
            page_obj = pdf.pages[item.page_num - 1].obj
            figure = pdf.make_indirect(
                Dictionary(
                    Type=Name.StructElem,
                    S=Name.Figure,
                    P=doc_elem,
                    Alt=String(item.text),
                    Pg=page_obj,
                )
            )
            figures.append(figure)

        doc_elem.K = figures
        struct_root.K = Array([doc_elem])
        root.StructTreeRoot = struct_root

        target_pdf = Path(target_pdf)
        target_pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(str(target_pdf))
    finally:
        pdf.close()
