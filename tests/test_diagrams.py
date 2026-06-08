"""Unit-tester för diagram-extraktion (offline — ingen API-trafik)."""
from __future__ import annotations

from pathlib import Path

import fitz

from src.diagrams import (
    MIN_CLUSTER_HEIGHT,
    MIN_CLUSTER_WIDTH,
    MIN_DRAWINGS_PER_CLUSTER,
    find_diagram_regions,
    render_and_save_region,
)


def test_find_regions_in_penningpolitisk_known_diagram_page(penningpolitisk_pdf: Path):
    """Sida 11 i penningpolitiska rapporten har två kända diagram bredvid varandra."""
    doc = fitz.open(penningpolitisk_pdf)
    try:
        page = doc.load_page(10)
        regions = find_diagram_regions(page, 11)
        assert len(regions) == 2, f"Förväntar 2 diagram på sida 11, fick {len(regions)}"
        for r in regions:
            assert r.bbox[2] - r.bbox[0] >= MIN_CLUSTER_WIDTH
            assert r.bbox[3] - r.bbox[1] >= MIN_CLUSTER_HEIGHT
            assert r.n_drawings >= MIN_DRAWINGS_PER_CLUSTER
    finally:
        doc.close()


def test_find_regions_splits_stacked_diagrams(penningpolitisk_pdf: Path):
    """Sida 68 har två diagram staplade vertikalt (Diagram 41 + 42)."""
    doc = fitz.open(penningpolitisk_pdf)
    try:
        page = doc.load_page(67)
        regions = find_diagram_regions(page, 68)
        assert len(regions) == 2, f"Förväntar 2 staplade diagram på sida 68, fick {len(regions)}"
        regions_sorted = sorted(regions, key=lambda r: r.bbox[1])
        assert regions_sorted[0].bbox[3] < regions_sorted[1].bbox[1]
    finally:
        doc.close()


def test_find_regions_skips_table_page(penningpolitisk_pdf: Path):
    """Sida 70 är en datatabell, inte diagram — ska ge 0 regioner."""
    doc = fitz.open(penningpolitisk_pdf)
    try:
        page = doc.load_page(69)
        regions = find_diagram_regions(page, 70)
        assert regions == [], f"Tabell-sida ska inte ge regioner, fick {len(regions)}"
    finally:
        doc.close()


def test_find_regions_skips_text_only_page(pentland_pdf: Path):
    """Pentland-artikeln har inga diagram — varje sida ska ge 0 regioner."""
    doc = fitz.open(pentland_pdf)
    try:
        total = 0
        for i, page in enumerate(doc, start=1):
            total += len(find_diagram_regions(page, i))
        assert total == 0, f"Förväntar 0 diagram i Pentland-PDF, fick {total}"
    finally:
        doc.close()


def test_render_region_produces_png(penningpolitisk_pdf: Path, tmp_path: Path):
    doc = fitz.open(penningpolitisk_pdf)
    try:
        page = doc.load_page(10)
        regions = find_diagram_regions(page, 11)
        assert regions
        out_dir = tmp_path / "diagrams"
        path = render_and_save_region(page, regions[0], out_dir)
        assert path.exists()
        assert path.stat().st_size > 1000
        assert path.suffix == ".png"
        assert regions[0].path == path
    finally:
        doc.close()
