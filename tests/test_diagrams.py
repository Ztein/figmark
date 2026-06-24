"""Unit tests for diagram extraction (offline — no API traffic)."""

from __future__ import annotations

import random
from pathlib import Path

import fitz

from figmark.diagrams import (
    MIN_CLUSTER_HEIGHT,
    MIN_CLUSTER_WIDTH,
    MIN_DRAWINGS_PER_CLUSTER,
    DiagramRegion,
    _close,
    _cluster_rects,
    find_diagram_regions,
    render_and_save_region,
    text_block_in_region,
)


def test_text_block_in_region_drops_internal_keeps_adjacent():
    """T-008: a label fully inside a diagram region is suppressed, but body text
    that merely abuts the (expanded) region is kept — never silently deleted."""
    region = DiagramRegion(page_num=1, index=1, bbox=(100, 100, 400, 400), n_drawings=20)
    # An internal label, fully inside the chart → suppressed.
    assert text_block_in_region((150, 150, 250, 170), [region]) is True
    # A body paragraph clipping only the bottom edge (≈20% inside) → kept.
    assert text_block_in_region((100, 380, 400, 480), [region]) is False
    # Fully outside → kept.
    assert text_block_in_region((100, 500, 400, 520), [region]) is False


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


def test_offpage_drawings_yield_no_degenerate_regions(tmp_path: Path):
    """Drawings placed above the page (negative y — crop marks, spill-over) must
    not produce degenerate regions: every returned bbox renders to a valid PNG.

    Regression for a real-world failure (BIS Annual Report): a cluster entirely
    off-page survived clamping with negative height and crashed the PNG writer
    with 'Invalid bandwriter header dimensions/setup'."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # A dense cluster of drawings ABOVE the page (negative y): 25 stacked thin
    # rects 3 px apart (within MERGE_DISTANCE), 300 px wide, ~75 px tall — passes
    # every cluster filter, but the whole cluster lies off-page.
    for i in range(25):
        y = -85 + i * 3
        page.draw_rect(fitz.Rect(100, y, 400, y + 2.5))
    # And a legitimate in-page cluster.
    for i in range(25):
        y = 200 + i * 3
        page.draw_rect(fitz.Rect(100, y, 400, y + 2.5))
    out = tmp_path / "offpage.pdf"
    doc.save(out)
    doc.close()

    reopened = fitz.open(out)
    try:
        page = reopened.load_page(0)
        regions = find_diagram_regions(page, 1)
        for r in regions:
            x0, y0, x1, y1 = r.bbox
            assert x1 > x0 and y1 > y0, f"degenerate region bbox: {r.bbox}"
            # The real proof: every region must actually render.
            path = render_and_save_region(page, r, tmp_path / "diagrams")
            assert path.exists() and path.stat().st_size > 0
    finally:
        reopened.close()


def test_large_diagram_payload_is_capped(tmp_path: Path, env_with_key, project_root: Path):
    """A huge rendered diagram must be resized below the API payload cap before
    being sent — exactly like raster images are.

    Regression for a real-world failure (BIS Annual Report 2024, page 115): a
    1 MB diagram PNG was base64'd raw and rejected by the endpoint (400/413)."""
    import os
    from types import SimpleNamespace

    from PIL import Image

    from figmark.config import load_config
    from figmark.describe import MAX_PAYLOAD_BYTES
    from figmark.diagrams import DiagramRegion, describe_diagram

    data = os.urandom(1500 * 1500 * 3)  # incompressible noise → big PNG
    img_path = tmp_path / "big.png"
    Image.frombytes("RGB", (1500, 1500), data).save(img_path)
    assert img_path.stat().st_size > MAX_PAYLOAD_BYTES, "test image is not 'too large'"

    captured = {}

    def create(model, max_tokens, messages, **kw):
        for part in messages[0]["content"]:
            if part["type"] == "image_url":
                captured["url_len"] = len(part["image_url"]["url"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="d"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    region = DiagramRegion(page_num=1, index=1, bbox=(0, 0, 10, 10), n_drawings=10, path=img_path)
    cfg = load_config(project_root / "config.example.yaml")

    describe_diagram(client, region, tmp_path / "desc.txt", cfg)
    # base64 expands by 4/3; the encoded payload must stay near the cap.
    assert captured["url_len"] < MAX_PAYLOAD_BYTES * 1.4, (
        f"diagram payload not capped: {captured['url_len']} chars"
    )


def _rand_rect(rng: random.Random) -> fitz.Rect:
    x = rng.uniform(0, 500)
    y = rng.uniform(0, 500)
    return fitz.Rect(x, y, x + rng.uniform(1, 60), y + rng.uniform(1, 60))


def _bruteforce_partition(rects: list[fitz.Rect], slack: float) -> set[frozenset[int]]:
    """All-pairs union-find — the reference the x-sweep must reproduce exactly."""
    n = len(rects)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if _close(rects[i], rects[j], slack):
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return {frozenset(g) for g in groups.values()}


def test_cluster_rects_matches_bruteforce_partition():
    """T-037: the near-linear x-sweep clustering must yield the identical partition
    as the original O(n²) all-pairs version, across many random layouts."""
    rng = random.Random(20260624)
    for _ in range(25):
        rects = [_rand_rect(rng) for _ in range(90)]
        slack = rng.uniform(0, 12)
        swept = {frozenset(g) for g in _cluster_rects(rects, slack)}
        assert swept == _bruteforce_partition(rects, slack)


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
