"""LIVE OCR-pipeline-tester.

Genererar en raster-PDF från en av testfilerna och kör hela pipelinen mot den
för att verifiera OCR-vägen — både Tesseract och Gemma-fallback.

Tesseract-vägen är gratis och lokal.
Gemma-fallback-vägen kostar API-pengar (testas med 1 sida).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import fitz
import pytest
import yaml

from src import main as main_module

pytestmark = pytest.mark.live


def _require_real_key():
    import os
    from dotenv import load_dotenv
    load_dotenv()
    key = os.environ.get("BERGET_API_KEY", "")
    if not key or key.startswith("sk-test") or key == "sk-your-key-here":
        pytest.fail(
            "\n\n" + "!" * 78 +
            "\n!!! BERGET_API_KEY saknas — OCR-fallback-testet kräver riktig nyckel.\n"
            + "!" * 78
        )


@pytest.fixture
def real_key():
    _require_real_key()


def _make_raster_pdf(source_pdf: Path, dest_pdf: Path, num_pages: int = 2, dpi: int = 200) -> None:
    """Rastrera num_pages första sidorna av source_pdf till en bilder-bara-PDF."""
    src = fitz.open(source_pdf)
    out = fitz.open()
    try:
        for i in range(min(num_pages, len(src))):
            page = src.load_page(i)
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            new_page = out.new_page(width=pix.width, height=pix.height)
            new_page.insert_image(new_page.rect, pixmap=pix)
        out.save(dest_pdf)
    finally:
        out.close()
        src.close()


def test_ocr_pipeline_with_tesseract(
    real_key, project_root: Path, etikprovning_pdf: Path, tmp_path: Path
):
    """Rastrera svensk PDF, kör pipelinen, verifiera att Tesseract läser svenska."""
    raster_pdf = tmp_path / "raster.pdf"
    _make_raster_pdf(etikprovning_pdf, raster_pdf, num_pages=2, dpi=200)

    output_root = tmp_path / "output"
    exit_code = main_module.run(
        pdf_path=raster_pdf,
        config_path=project_root / "config.yaml",
        output_root=output_root,
    )
    assert exit_code == 0

    raw_text = (output_root / raster_pdf.stem / "raw_text.txt").read_text(encoding="utf-8")
    assert len(raw_text.strip()) > 200, (
        f"Tesseract producerade orimligt lite text ({len(raw_text)} tecken) — "
        f"har du installerat språkpaketet 'swe'?"
    )
    # Svensk text bör innehålla å/ä/ö någonstans
    assert any(c in raw_text.lower() for c in "åäö"), (
        f"Hittar inga svenska tecken i OCR-resultatet — fel språkpaket?\n"
        f"Första 500 tecknen:\n{raw_text[:500]}"
    )
    # Inga bilder ska syntolkas i OCR-läge (hela sidan = en bild = hoppas över)
    descriptions_dir = output_root / raster_pdf.stem / "descriptions"
    if descriptions_dir.exists():
        assert list(descriptions_dir.iterdir()) == [], (
            "OCR-läget ska inte syntolka sid-stora bilder"
        )


def test_ocr_pipeline_fallback_to_gemma(
    real_key, project_root: Path, etikprovning_pdf: Path, tmp_path: Path
):
    """Tvinga fram Gemma-OCR-fallback genom orimligt hög Tesseract-tröskel.

    Använder bara 1 sida för att hålla nere kostnaden — en (1) API-anrop till Gemma.
    """
    # Rastrera 1 sida
    raster_pdf = tmp_path / "raster_fallback.pdf"
    _make_raster_pdf(etikprovning_pdf, raster_pdf, num_pages=1, dpi=200)

    # Skapa modifierad config som tvingar fallback
    with (project_root / "config.yaml").open("r", encoding="utf-8") as f:
        raw_cfg = yaml.safe_load(f)
    raw_cfg["ocr"]["min_chars_per_page"] = 999_999  # Tesseract kan aldrig nå detta
    raw_cfg["ocr"]["min_mean_confidence"] = 0  # bara teckenkravet ska trigga
    forced_cfg = tmp_path / "forced_fallback.yaml"
    with forced_cfg.open("w", encoding="utf-8") as f:
        yaml.safe_dump(raw_cfg, f, allow_unicode=True)

    output_root = tmp_path / "output"
    exit_code = main_module.run(
        pdf_path=raster_pdf,
        config_path=forced_cfg,
        output_root=output_root,
    )
    assert exit_code == 0

    raw_text = (output_root / raster_pdf.stem / "raw_text.txt").read_text(encoding="utf-8")
    # Gemma-OCR-svaret ska finnas i raw_text (utan [Bild:]-platshållare eftersom OCR-läget
    # inte syntolkar sid-stora bilder)
    assert len(raw_text.strip()) > 100, (
        f"Gemma-OCR-fallback gav orimligt lite text:\n{raw_text!r}"
    )
    # Svensk text-heuristik
    assert any(c in raw_text.lower() for c in "åäö") or any(
        w in raw_text.lower() for w in [" och ", " att ", " som "]
    ), f"Gemma-OCR-resultatet ser inte svenskt ut:\n{raw_text[:500]}"
    print(f"\n--- Gemma-OCR-fallback resultat (första 400 tecken) ---\n{raw_text[:400]}\n")
