"""LIVE OCR pipeline tests.

Generate a raster PDF from one of the sample documents and run the whole pipeline
against it to verify the OCR path — both Tesseract and the vision-OCR fallback.

The Tesseract path is free and local.
The vision-OCR fallback path costs API money (tested with 1 page).
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
import yaml

from figmark import main as main_module

pytestmark = pytest.mark.live


def _require_real_key():
    import os

    from dotenv import load_dotenv

    load_dotenv()
    key = os.environ.get("BERGET_API_KEY", "")
    if not key or key.startswith("sk-test") or key == "sk-your-key-here":
        pytest.fail(
            "\n\n"
            + "!" * 78
            + "\n!!! BERGET_API_KEY is missing — the OCR fallback test needs a real key.\n"
            + "!" * 78
        )


@pytest.fixture
def real_key():
    _require_real_key()


def _make_raster_pdf(source_pdf: Path, dest_pdf: Path, num_pages: int = 2, dpi: int = 200) -> None:
    """Rasterize the first num_pages of source_pdf into an images-only PDF."""
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


def test_ocr_pipeline_with_tesseract(real_key, project_root: Path, guide_pdf: Path, tmp_path: Path):
    """Rasterize a Swedish PDF, run the pipeline, verify Tesseract reads Swedish."""
    raster_pdf = tmp_path / "raster.pdf"
    _make_raster_pdf(guide_pdf, raster_pdf, num_pages=2, dpi=200)

    output_root = tmp_path / "output"
    exit_code = main_module.run(
        pdf_path=raster_pdf,
        config_path=project_root / "config.yaml",
        output_root=output_root,
    )
    assert exit_code == 0

    raw_text = (output_root / raster_pdf.stem / "raw_text.txt").read_text(encoding="utf-8")
    assert len(raw_text.strip()) > 200, (
        f"Tesseract produced implausibly little text ({len(raw_text)} chars) — "
        f"is the 'swe' language pack installed?"
    )
    # Swedish text should contain å/ä/ö somewhere.
    assert any(c in raw_text.lower() for c in "åäö"), (
        f"No Swedish characters in the OCR result — wrong language pack?\n"
        f"First 500 chars:\n{raw_text[:500]}"
    )
    # No images should be described in OCR mode (the whole page is one image, skipped).
    descriptions_dir = output_root / raster_pdf.stem / "descriptions"
    if descriptions_dir.exists():
        assert list(descriptions_dir.iterdir()) == [], (
            "OCR mode should not describe page-sized images"
        )


def test_ocr_pipeline_fallback_to_vision(
    real_key, project_root: Path, guide_pdf: Path, tmp_path: Path
):
    """Force the vision-OCR fallback via an absurdly high Tesseract threshold.

    Uses only 1 page to keep cost down — a single API call to the vision model.
    """
    raster_pdf = tmp_path / "raster_fallback.pdf"
    _make_raster_pdf(guide_pdf, raster_pdf, num_pages=1, dpi=200)

    # Create a modified config that forces the fallback.
    with (project_root / "config.yaml").open("r", encoding="utf-8") as f:
        raw_cfg = yaml.safe_load(f)
    raw_cfg["ocr"]["min_chars_per_page"] = 999_999  # Tesseract can never reach this
    raw_cfg["ocr"]["min_mean_confidence"] = 0  # only the char requirement should trigger
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
    assert len(raw_text.strip()) > 100, (
        f"The vision-OCR fallback produced implausibly little text:\n{raw_text!r}"
    )
    # Swedish-text heuristic.
    assert any(c in raw_text.lower() for c in "åäö") or any(
        w in raw_text.lower() for w in [" och ", " att ", " som "]
    ), f"The vision-OCR result does not look Swedish:\n{raw_text[:500]}"
    print(f"\n--- Vision-OCR fallback result (first 400 chars) ---\n{raw_text[:400]}\n")
