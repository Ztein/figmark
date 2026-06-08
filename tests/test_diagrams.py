"""Unit tests for diagram extraction (offline — no API traffic)."""

from __future__ import annotations

from pathlib import Path

import fitz

from figmark.diagrams import (
    MIN_CLUSTER_HEIGHT,
    MIN_CLUSTER_WIDTH,
    MIN_DRAWINGS_PER_CLUSTER,
    find_diagram_regions,
    render_and_save_region,
)


def test_find_regions_in_report_known_diagram_page(report_pdf: Path):
    """Page 11 of the monetary-policy report has two known charts side by side."""
    doc = fitz.open(report_pdf)
    try:
        page = doc.load_page(10)
        regions = find_diagram_regions(page, 11)
        assert len(regions) == 2, f"Expected 2 diagrams on page 11, got {len(regions)}"
        for r in regions:
            assert r.bbox[2] - r.bbox[0] >= MIN_CLUSTER_WIDTH
            assert r.bbox[3] - r.bbox[1] >= MIN_CLUSTER_HEIGHT
            assert r.n_drawings >= MIN_DRAWINGS_PER_CLUSTER
    finally:
        doc.close()


def test_find_regions_splits_stacked_diagrams(report_pdf: Path):
    """Page 68 has two charts stacked vertically."""
    doc = fitz.open(report_pdf)
    try:
        page = doc.load_page(67)
        regions = find_diagram_regions(page, 68)
        assert len(regions) == 2, f"Expected 2 stacked diagrams on page 68, got {len(regions)}"
        regions_sorted = sorted(regions, key=lambda r: r.bbox[1])
        assert regions_sorted[0].bbox[3] < regions_sorted[1].bbox[1]
    finally:
        doc.close()


def test_find_regions_skips_table_page(report_pdf: Path):
    """Page 70 is a data table, not a chart — should yield 0 regions."""
    doc = fitz.open(report_pdf)
    try:
        page = doc.load_page(69)
        regions = find_diagram_regions(page, 70)
        assert regions == [], f"A table page should yield no regions, got {len(regions)}"
    finally:
        doc.close()


def test_find_regions_skips_text_only_page(tmp_path: Path):
    """A text-only page (no vector drawings) must yield 0 regions.

    Built synthetically so the test is self-contained and deterministic.
    """
    doc = fitz.open()
    page = doc.new_page()
    for i in range(40):
        page.insert_text((72, 72 + i * 16), f"Line {i}: lorem ipsum dolor sit amet.")
    out = tmp_path / "text_only.pdf"
    doc.save(out)
    doc.close()

    reopened = fitz.open(out)
    try:
        total = sum(len(find_diagram_regions(p, i)) for i, p in enumerate(reopened, start=1))
        assert total == 0, f"Expected 0 diagrams on a text-only page, got {total}"
    finally:
        reopened.close()


def test_render_region_produces_png(report_pdf: Path, tmp_path: Path):
    doc = fitz.open(report_pdf)
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
