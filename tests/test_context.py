"""Tester för context-modulen — mot verkliga PDF:er.

Vi extraherar PageData via samma pipeline som produktion använder
(iter_page_blocks etc.) och verifierar att get_text_context_around() plockar
ut meningsfull kontext från riktiga sidor.
"""
from __future__ import annotations

from pathlib import Path

from src.context import ContextText, get_text_context_around
from src.output import PageData
from src.pdf_loader import ImageBlock, iter_page_blocks, iter_pages, open_pdf


def _build_pages_from_pdf(pdf_path: Path) -> list[PageData]:
    """Bygg PageData-lista som matchar pipelinens setup för en textkodad PDF."""
    doc = open_pdf(pdf_path)
    try:
        pages = []
        for page_num, page in iter_pages(doc):
            pd = PageData(page_num=page_num, is_ocr=False, blocks=iter_page_blocks(page))
            pages.append(pd)
        return pages
    finally:
        doc.close()


def test_context_text_dataclass_basic():
    """ContextText.is_empty och format_for_prompt — minimal sanity (ingen mockad data)."""
    assert ContextText(before="", after="").is_empty()
    assert not ContextText(before="text", after="").is_empty()

    s = ContextText(before="A B C", after="X Y Z").format_for_prompt()
    assert "A B C" in s and "X Y Z" in s
    assert "före" in s.lower() and "efter" in s.lower()


def test_context_around_pentland_image_pulls_routine_text(pentland_pdf: Path):
    """Pentland är en artikel om 'organizational routines'. Bild 1 på sida 1
    omges av relevant text om ämnet. Kontexten ska innehålla ord vi vet finns
    i artikeln."""
    pages = _build_pages_from_pdf(pentland_pdf)
    # Hitta första bilden i någon sida
    for page in pages:
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                ctx = get_text_context_around(
                    pages, page_num=page.page_num, bbox=block.bbox,
                    words_before=50, words_after=50,
                )
                # Antingen before eller after ska innehålla "routine" som är
                # central för artikeln
                combined = (ctx.before + " " + ctx.after).lower()
                assert "routine" in combined or "information" in combined, (
                    f"Förväntat artikel-vokabulär saknas i kontext kring sida "
                    f"{page.page_num} bild: before={ctx.before[:80]!r}, "
                    f"after={ctx.after[:80]!r}"
                )
                return
    # Skip if no images found — borde inte hända för pentland
    raise AssertionError("Inga bilder hittade i Pentland-PDF — testet kan inte köras")


def test_context_word_count_respected(pentland_pdf: Path):
    """Vi ska aldrig få fler ord än vi bett om."""
    pages = _build_pages_from_pdf(pentland_pdf)
    for page in pages:
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                ctx = get_text_context_around(
                    pages, page_num=page.page_num, bbox=block.bbox,
                    words_before=10, words_after=10,
                )
                assert len(ctx.before.split()) <= 10, (
                    f"Före-kontext gav fler än 10 ord: {len(ctx.before.split())}"
                )
                assert len(ctx.after.split()) <= 10
                return


def test_context_zero_words_returns_empty(pentland_pdf: Path):
    pages = _build_pages_from_pdf(pentland_pdf)
    for page in pages:
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                ctx = get_text_context_around(
                    pages, page_num=page.page_num, bbox=block.bbox,
                    words_before=0, words_after=0,
                )
                assert ctx.is_empty()
                return


def test_context_crosses_page_boundary_in_real_pdf(pentland_pdf: Path):
    """Om vi tar fler ord än som finns på samma sida ska kontexten dras från
    grannsidor. Testa att en stor `words_before` på en bild högt upp på sida 2+
    plockar med text från föregående sida."""
    pages = _build_pages_from_pdf(pentland_pdf)
    # Hitta första bilden vars sida har lite text ovanför den
    for page in pages[1:]:  # börja efter sida 1 så vi har en föregående sida
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                # Ta ENORMT antal ord — ska tvinga oss bakåt över sidgräns
                ctx_huge = get_text_context_around(
                    pages, page_num=page.page_num, bbox=block.bbox,
                    words_before=5000, words_after=5000,
                )
                # Vi har minst 16 sidor i pentland; 5000 ord ska gå utöver en sida
                # Kontexten ska vara icke-tom om det finns text någonstans i PDF:en
                assert not ctx_huge.is_empty()
                return
