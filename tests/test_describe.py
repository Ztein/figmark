"""Tester för describe-modulen — mot verkliga PDF:er.

Cache-beteende och prompt-bygge täcks av live-pipeline-tester i test_pipeline.py
(`test_pipeline_cache_no_extra_api_calls_on_rerun` etc.). Här testar vi bara
det som inte ENBART hör hemma i pipeline-nivå: payload-prepareringen.
"""
from __future__ import annotations

from pathlib import Path

import fitz

from src.describe import MAX_PAYLOAD_BYTES, _prepare_image_for_api


def _extract_first_image(pdf_path: Path, out_path: Path) -> Path:
    """Plocka första raster-bilden ur PDF:ens första sida som har en."""
    doc = fitz.open(pdf_path)
    try:
        for page in doc:
            images = page.get_images(full=True)
            if not images:
                continue
            xref = images[0][0]
            base = doc.extract_image(xref)
            target = out_path.with_suffix(f".{base['ext']}")
            target.write_bytes(base["image"])
            return target
        raise RuntimeError(f"Hittade ingen bild i {pdf_path.name}")
    finally:
        doc.close()


def test_prepare_pentland_logo_passes_through_unchanged(
    pentland_pdf: Path, tmp_path: Path
):
    """Pentland-omslagslogotyperna är små (< 100 KB). Ska skickas oförändrade."""
    img_path = _extract_first_image(pentland_pdf, tmp_path / "pentland_first")
    assert img_path.stat().st_size <= MAX_PAYLOAD_BYTES

    raw = img_path.read_bytes()
    payload, mime = _prepare_image_for_api(img_path)
    assert payload == raw, "Liten bild ska inte recompressas"
    # Mime ska matcha original-formatet
    assert mime.startswith("image/")


def test_prepare_etikprovning_cover_image_gets_resized(
    etikprovning_pdf: Path, tmp_path: Path
):
    """Regression mot 413-bug: etikprövning sida 1 omslagsbild (~917 KB PNG)
    ska skalas ner under MAX_PAYLOAD_BYTES innan API-anrop."""
    img_path = _extract_first_image(etikprovning_pdf, tmp_path / "etik_first")
    assert img_path.stat().st_size > MAX_PAYLOAD_BYTES, (
        f"Test-bilden är inte längre 'för stor' — uppdatera testet "
        f"om PDF:en har bytts ut. Storlek: {img_path.stat().st_size} B"
    )

    payload, mime = _prepare_image_for_api(img_path)
    assert len(payload) <= MAX_PAYLOAD_BYTES
    assert mime == "image/jpeg"  # konvertering till JPEG vid resize


def test_prepare_penningpolitisk_omslag_handled(
    penningpolitisk_pdf: Path, tmp_path: Path
):
    """Penningpolitiska har också raster-bilder på omslaget. De ska gå igenom
    pipelinen utan att överskrida API:ts payload-tak."""
    img_path = _extract_first_image(penningpolitisk_pdf, tmp_path / "penning_first")
    payload, mime = _prepare_image_for_api(img_path)
    assert len(payload) <= MAX_PAYLOAD_BYTES, (
        f"Penningpolitiska första bild blev för stor: {len(payload)} B"
    )
