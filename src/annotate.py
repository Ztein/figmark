"""Skriv in syntolkningar som text-annotations i en kopia av PDF:en.

PyMuPDF:s text-annotation (`page.add_text_annot`) skapar en "sticky note"-ikon
på given position. Innehållet visas vid hover/klick i PDF-läsare, och de flesta
skärmläsare (NVDA, JAWS) plockar upp /Contents-fältet.

Detta är MVP-tillgänglighet. För riktig PDF/UA — se T-004.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class AnnotationItem:
    """En syntolkning att lägga in som annotation i en PDF."""
    page_num: int                                              # 1-indexerat
    bbox: tuple[float, float, float, float]                    # bildens position i PDF-koord
    text: str                                                  # själva syntolkningen
    kind: str                                                  # "Bild" eller "Diagram"


def annotate_pdf(
    source_pdf: Path,
    target_pdf: Path,
    items: list[AnnotationItem],
) -> None:
    """Skapa en kopia av source_pdf med text-annotations för varje item.

    Källfilen lämnas orörd. Om items är tom blir target en ren kopia.
    Failar tydligt om en items.page_num ligger utanför PDF:ens sidor.
    """
    doc = fitz.open(source_pdf)
    try:
        n_pages = len(doc)
        # Validera ALLA items före vi börjar skriva — annars riskerar vi en
        # halvfärdig output om något item är felaktigt.
        for item in items:
            if item.page_num < 1 or item.page_num > n_pages:
                raise ValueError(
                    f"AnnotationItem page_num={item.page_num} ligger utanför "
                    f"PDF:ens sidor (1..{n_pages})"
                )

        for item in items:
            page = doc.load_page(item.page_num - 1)
            point = fitz.Point(item.bbox[0], item.bbox[1])
            annot = page.add_text_annot(point, item.text)
            # Sätt title via dict-API (keyword-args kraschar i PyMuPDF 1.27)
            info = annot.info
            info["title"] = f"Syntolkning av {item.kind}"
            info["content"] = item.text
            annot.set_info(info)

        target_pdf.parent.mkdir(parents=True, exist_ok=True)
        # garbage=4 + clean=True rensar upp objektgrafen så konsumenter med
        # gammal/sträng PyMuPDF inte kraschar på inkonsekventa annot-references.
        doc.save(target_pdf, garbage=4, clean=True, deflate=True)
    finally:
        doc.close()
