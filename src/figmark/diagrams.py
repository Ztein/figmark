"""Diagram extraction via PyMuPDF drawing clustering.

Central-bank and similar agency reports embed vector charts (matplotlib exported
to PDF path commands) that page.get_images() does not catch. This module finds
diagram regions by clustering drawings spatially and expands the bbox to capture
axis titles and source lines.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

import fitz

from .config import Config
from .context import ContextText
from .describe import _prepare_image_for_api, compose_prompt, truncation_marker

logger = logging.getLogger("figmark.diagrams")

# ============================================================================
# Technical constants for the clustering pipeline. Tune here if a specific PDF
# type needs it. Empirically calibrated against a central-bank monetary-policy
# report (vector charts from matplotlib).
# ============================================================================

# Pages with fewer drawings than this are not examined (text-heavy pages)
MIN_DRAWINGS_PER_PAGE = 30
# Drawings below this pixel size in BOTH dimensions do not count (specks).
# A drawing below it in exactly ONE dimension is an axis-aligned hairline —
# LibreOffice/TikZ draw chart axes and gridlines as zero-thickness strokes
# (T-055). Lines join clusters (they carry the chart's connectivity) but do
# not gate them: see MIN_SOLID_DRAWINGS_PER_CLUSTER.
MIN_DRAWING_DIM = 2
# Drawings larger than X% of the page area are skipped (background boxes)
MAX_DRAWING_AREA_RATIO = 0.4
# Drawings within this pixel distance are joined into the same cluster
MERGE_DISTANCE = 3
# A cluster must contain at least this many drawings
MIN_DRAWINGS_PER_CLUSTER = 8
# ... of which at least this many must be non-line (solid) members. Bar/pie/
# area charts pass (bars, wedges, legend chips are fills); a pure ruled grid
# (only hairlines) fails. Bench-derived (T-055): the smallest corpus positive,
# a 4-bar LO chart, has exactly 4 solids; line-only "charts" (an axis frame
# with no data marks) are indistinguishable from ruled grids and stay out.
MIN_SOLID_DRAWINGS_PER_CLUSTER = 4
# A candidate region is NOT a chart if it substantially overlaps a table-like
# find_tables candidate — ruled/zebra slide tables cluster exactly like charts
# (row fills = solids), and T-031's table path owns them. "Table-like" is
# deliberately laxer than tables.py's keep gates (suppression needs less
# evidence than emission): >= 3 rows, >= 2 cols, and a cell fill ratio the
# bench separated cleanly (charts' grid-junk candidates measured <= 36%
# filled, real tables >= 50% — threshold set between, T-055).
TABLE_SUPPRESS_MIN_ROWS = 3
TABLE_SUPPRESS_MIN_COLS = 2
TABLE_SUPPRESS_MIN_FILL = 0.45
TABLE_SUPPRESS_MIN_OVERLAP = 0.5
# A multi-panel chart grid can satisfy the grid test above (panel frames form a
# ruled 2xN "table" whose cells are full of axis text). What real data tables
# never contain is *sloped or curved* vector content — their fills and rules
# are all axis-aligned — while chart panels have line series, fan polygons or
# pie arcs. Bench: every labelled table candidate measured 0 sloped members
# inside; every chart-grid candidate measured >= 3 (T-055). A candidate with
# this many sloped members inside is a chart grid, not a table, and must not
# suppress. Residual risk: a *pure bar chart* under a table-like candidate has
# 0 sloped members too — no such page exists in the corpus (bar-chart pages
# produce no table candidate), noted here for honesty.
TABLE_SUPPRESS_MAX_SLOPED = 3
# Clusters must be at least this large (px)
MIN_CLUSTER_WIDTH = 80
MIN_CLUSTER_HEIGHT = 60
# Internal y-gaps larger than this split the cluster (stacked charts)
INTERNAL_Y_GAP_SPLIT = 40
# Extra px around the clustering bbox before text expansion
PADDING = 6
# Neighbouring text blocks (axis title/source line) within this many px are included
TEXT_EXPAND_DISTANCE = 30
# DPI for rendering the diagram image sent to the model
RENDER_DPI = 200
# Cap for a diagram description
MAX_TOKENS = 1200
# Inline placeholder used in the assembled plain text
PLACEHOLDER = "[Diagram: {description}]"


@dataclass
class DiagramRegion:
    page_num: int  # 1-indexed
    index: int  # 1-indexed within the page
    bbox: tuple[float, float, float, float]
    n_drawings: int
    path: Path | None = None  # filled in when the image is saved


def _close(r1: fitz.Rect, r2: fitz.Rect, slack: float) -> bool:
    return not (
        r1.x1 + slack < r2.x0
        or r2.x1 + slack < r1.x0
        or r1.y1 + slack < r2.y0
        or r2.y1 + slack < r1.y0
    )


def _cluster_rects(rects: list[fitz.Rect], merge_distance: float) -> list[list[int]]:
    """Union-find clustering of rectangles by spatial proximity.

    Connectivity is the ``_close`` relation (bboxes within ``merge_distance``).
    Rather than test all O(n²) pairs, sweep left to right by ``x0`` keeping an
    "active" set of rects whose right edge is still within reach; a rect can only
    be close to an active one. This yields the *identical* connected components as
    the brute-force pairing (a pair pruned by the sweep can never satisfy
    ``_close``), but is near-linear when drawings are spatially spread — the common
    case on a chart page — instead of quadratic. (T-037)
    """
    n = len(rects)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    order = sorted(range(n), key=lambda i: rects[i].x0)
    active: list[int] = []  # indices whose right edge may still reach a later rect
    for idx in order:
        r = rects[idx]
        still_active: list[int] = []
        for j in active:
            # Once a rect's right edge + slack is left of r.x0, it (and every later
            # rect, all with larger x0) can never be close again — drop it.
            if rects[j].x1 + merge_distance < r.x0:
                continue
            still_active.append(j)
            if _close(rects[j], r, merge_distance):
                union(j, idx)
        still_active.append(idx)
        active = still_active

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _split_by_y_gap(
    group_rects: list[tuple[fitz.Rect, bool]], min_gap: float
) -> list[list[tuple[fitz.Rect, bool]]]:
    """Split a cluster if it has an internal y-gap larger than min_gap.

    Items are ``(rect, is_solid)`` pairs so the solid count survives the split.
    """
    if len(group_rects) < 2:
        return [group_rects]
    by_y = sorted(group_rects, key=lambda item: item[0].y0)
    splits: list[list[tuple[fitz.Rect, bool]]] = []
    current = [by_y[0]]
    current_max_y = by_y[0][0].y1
    for item in by_y[1:]:
        r = item[0]
        gap = r.y0 - current_max_y
        if gap > min_gap:
            splits.append(current)
            current = [item]
            current_max_y = r.y1
        else:
            current.append(item)
            current_max_y = max(current_max_y, r.y1)
    splits.append(current)
    return splits


def _has_sloped_content(drawing: dict) -> bool:
    """True if the drawing's path has a curve or a non-axis-aligned line —
    chart content (line series, fan polygons, pie arcs); data-table fills and
    rules are always axis-aligned (T-055)."""
    for item in drawing.get("items", []):
        op = item[0]
        if op == "c":
            return True
        if op == "l" and abs(item[1].x - item[2].x) > 1 and abs(item[1].y - item[2].y) > 1:
            return True
    return False


def _table_like_rects(page: fitz.Page) -> list[fitz.Rect]:
    """Bboxes of find_tables candidates that look like real data tables (T-055).

    Used to suppress diagram clusters over ruled/zebra tables. The bar is laxer
    than tables.py's keep gates on purpose — and chart-internal grid junk stays
    below the fill threshold, so genuine charts are not suppressed.
    """
    try:
        finder = page.find_tables()
    except Exception as e:  # noqa: BLE001 — a page quirk must not kill detection
        logger.warning("find_tables raised during diagram suppression (%s)", e)
        return []
    out: list[fitz.Rect] = []
    for t in finder.tables:
        # The full grid, empty rows included: dropping them inflates the fill
        # ratio of sparse chart grids (transformer attention figures measure
        # ~20% on the full grid but ~45% row-filtered) and causes real-chart
        # suppression. Zebra tables measure >= 50% either way.
        rows = [[(c or "").strip() for c in row] for row in t.extract()]
        if len(rows) < TABLE_SUPPRESS_MIN_ROWS:
            continue
        ncols = max(len(r) for r in rows)
        cells = [c for row in rows for c in row]
        if ncols < TABLE_SUPPRESS_MIN_COLS or not cells:
            continue
        if sum(1 for c in cells if c) / len(cells) >= TABLE_SUPPRESS_MIN_FILL:
            out.append(fitz.Rect(t.bbox))
    return out


def _expand_with_neighboring_text(
    page: fitz.Page,
    bbox: fitz.Rect,
    max_distance: float,
    y_min_limit: float,
    y_max_limit: float,
) -> fitz.Rect:
    """Expand the bbox vertically to include neighbouring text blocks.

    Bounded by y_min/max_limit so two diagrams do not merge into one.
    """
    expanded = fitz.Rect(bbox)
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        tb = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
        if tb.width == 0 or tb.height == 0:
            continue
        horiz_overlap = min(bbox.x1, tb.x1) - max(bbox.x0, tb.x0)
        if horiz_overlap < 0.3 * tb.width:
            continue
        if tb.y1 <= bbox.y0 and bbox.y0 - tb.y1 <= max_distance and tb.y0 >= y_min_limit:
            expanded |= tb
        elif tb.y0 >= bbox.y1 and tb.y0 - bbox.y1 <= max_distance and tb.y1 <= y_max_limit:
            expanded |= tb
    return expanded


def find_diagram_regions(page: fitz.Page, page_num: int) -> list[DiagramRegion]:
    """Find diagram regions on a page.

    Pipeline: filter drawings → cluster spatially → split on internal y-gap →
    expand bbox with neighbouring text → return sorted in reading order.
    """
    drawings = page.get_drawings()
    if len(drawings) < MIN_DRAWINGS_PER_PAGE:
        return []

    page_area = page.rect.width * page.rect.height
    max_drawing_area = MAX_DRAWING_AREA_RATIO * page_area

    rects: list[fitz.Rect] = []
    solid: list[bool] = []
    sloped: list[bool] = []
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        thin_w = r.width < MIN_DRAWING_DIM
        thin_h = r.height < MIN_DRAWING_DIM
        if thin_w and thin_h:
            continue  # speck/decoration
        if r.width * r.height > max_drawing_area:
            continue  # page background/frame
        # Axis-aligned hairlines (LO/TikZ axes, gridlines) join clusters but
        # don't gate them (T-055).
        rects.append(fitz.Rect(r))
        solid.append(not (thin_w or thin_h))
        sloped.append(_has_sloped_content(d))

    if not rects:
        return []

    groups = _cluster_rects(rects, MERGE_DISTANCE)

    raw_bboxes: list[tuple[fitz.Rect, int]] = []
    for group in groups:
        if len(group) < MIN_DRAWINGS_PER_CLUSTER:
            continue
        cluster_items = [(rects[i], solid[i]) for i in group]
        for sub_items in _split_by_y_gap(cluster_items, INTERNAL_Y_GAP_SPLIT):
            if len(sub_items) < MIN_DRAWINGS_PER_CLUSTER:
                continue
            if sum(1 for _, s in sub_items if s) < MIN_SOLID_DRAWINGS_PER_CLUSTER:
                continue  # hairlines only ≈ ruled grid, not a chart
            sub = [r for r, _ in sub_items]
            x0 = min(r.x0 for r in sub)
            y0 = min(r.y0 for r in sub)
            x1 = max(r.x1 for r in sub)
            y1 = max(r.y1 for r in sub)
            if x1 - x0 < MIN_CLUSTER_WIDTH or y1 - y0 < MIN_CLUSTER_HEIGHT:
                continue
            bbox = fitz.Rect(
                max(0, x0 - PADDING),
                max(0, y0 - PADDING),
                min(page.rect.width, x1 + PADDING),
                min(page.rect.height, y1 + PADDING),
            )
            raw_bboxes.append((bbox, len(sub)))

    raw_bboxes.sort(key=lambda b: b[0].y0)
    regions: list[DiagramRegion] = []
    for i, (bbox, n_draw) in enumerate(raw_bboxes):
        y_min_limit = 0.0
        y_max_limit = page.rect.height
        for j, (other, _) in enumerate(raw_bboxes):
            if j == i:
                continue
            horiz_overlap = min(bbox.x1, other.x1) - max(bbox.x0, other.x0)
            if horiz_overlap < 0.3 * min(bbox.width, other.width):
                continue
            if other.y1 <= bbox.y0:
                y_min_limit = max(y_min_limit, other.y1 + 4)
            elif other.y0 >= bbox.y1:
                y_max_limit = min(y_max_limit, other.y0 - 4)

        expanded = _expand_with_neighboring_text(
            page, bbox, TEXT_EXPAND_DISTANCE, y_min_limit, y_max_limit
        )
        expanded &= page.rect
        # Clusters can lie (partly) outside the page — crop marks, spill-over
        # content with negative coordinates. After clipping to the page, a
        # degenerate or tiny remnant is not a chart: rendering it crashes the
        # PNG writer ("Invalid bandwriter header dimensions/setup").
        if expanded.is_empty or expanded.width < 1 or expanded.height < 1:
            continue
        regions.append(
            DiagramRegion(
                page_num=page_num,
                index=len(regions) + 1,
                bbox=(expanded.x0, expanded.y0, expanded.x1, expanded.y1),
                n_drawings=n_draw,
            )
        )

    # A region sitting on a real data table is the table path's business
    # (T-031/T-055) — zebra row fills cluster exactly like chart bars, and
    # describing a table as a picture double-represents it.
    if regions:
        suppressors = []
        for s in _table_like_rects(page):
            sloped_inside = sum(
                1
                for i, rect in enumerate(rects)
                if sloped[i] and (rect & s).get_area() >= 0.5 * max(rect.get_area(), 1e-9)
            )
            if sloped_inside < TABLE_SUPPRESS_MAX_SLOPED:
                suppressors.append(s)
        if suppressors:
            kept: list[DiagramRegion] = []
            for r in regions:
                region_rect = fitz.Rect(r.bbox)
                area = region_rect.get_area()
                overlap = max((region_rect & s).get_area() for s in suppressors)
                if area > 0 and overlap / area >= TABLE_SUPPRESS_MIN_OVERLAP:
                    logger.info(
                        "page %d: diagram candidate %s suppressed — overlaps a data table",
                        page_num,
                        tuple(round(v) for v in r.bbox),
                    )
                    continue
                kept.append(r)
            regions = kept

    regions.sort(key=lambda r: (round(r.bbox[1] / 10), r.bbox[0]))
    for i, r in enumerate(regions, start=1):
        r.index = i
    return regions


# A text block this fraction inside a diagram region is the diagram's own label
# text (redundant with the rendered image + description). High, deliberately: the
# region bbox is expanded to grab axis titles/source lines, so a body paragraph
# that merely abuts the chart is only partly inside and must be kept, not deleted.
TEXT_IN_REGION_OVERLAP = 0.8


def text_block_in_region(
    bbox, regions: list[DiagramRegion], min_overlap: float = TEXT_IN_REGION_OVERLAP
) -> bool:
    """True if a text block lies mostly inside a diagram region — its content is the
    diagram's internal labels, which leak into the body otherwise. (T-008)
    """
    r = fitz.Rect(bbox)
    area = abs(r.width * r.height)
    if area <= 0:
        return False
    for region in regions:
        inter = r & fitz.Rect(region.bbox)
        if not inter.is_empty and abs(inter.width * inter.height) / area >= min_overlap:
            return True
    return False


def render_and_save_region(
    page: fitz.Page,
    region: DiagramRegion,
    out_dir: Path,
) -> Path:
    """Render the region bbox as PNG and return the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
    pix = page.get_pixmap(
        matrix=matrix,
        clip=fitz.Rect(*region.bbox),
        alpha=False,
    )
    fname = f"page-{region.page_num:03d}-diagram-{region.index:02d}.png"
    path = out_dir / fname
    path.write_bytes(pix.tobytes("png"))
    region.path = path
    return path


def describe_diagram(
    client,
    region: DiagramRegion,
    description_path: Path,
    cfg: Config,
    context: ContextText | None = None,
    doc_summary: str | None = None,
    language: str | None = None,
) -> str:
    """Send the diagram image to the model with the diagram-specific prompt.

    Cache: if description_path exists and is non-empty, read it from disk.
    The document summary and any text context are prepended before the task.
    The significance skip gate follows ``cfg.significance`` here too: the eval
    corpus showed ~2 % of clustered regions are vector logos, not charts, so the
    gate lets the model return [SKIP] for those instead of captioning a logo. (T-023)
    """
    if description_path.exists():
        cached = description_path.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    if region.path is None:
        raise RuntimeError(f"Region {region.page_num}.{region.index} has no saved path")

    # Resize/re-encode under the API payload cap — large chart regions rendered
    # at 200 DPI can exceed it (BIS AR 2024 p.115: a 1 MB PNG → 400 from the API).
    img_bytes, mime = _prepare_image_for_api(region.path)
    data_uri = f"data:{mime};base64," + base64.b64encode(img_bytes).decode("ascii")

    user_text = compose_prompt(
        cfg.diagrams.prompt,
        doc_summary=doc_summary,
        context=context,
        significance=cfg.significance.enabled,
        language=language if language is not None else cfg.language.output,
    )

    response = client.chat.completions.create(
        model=cfg.api.model,
        temperature=cfg.api.temperature,
        max_tokens=MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    )
    choice = response.choices[0]
    text = (choice.message.content or "").strip()
    if not text:
        raise RuntimeError(
            f"The API returned empty content for diagram {region.path.name} "
            f"(model={cfg.api.model})."
        )
    truncated = getattr(choice, "finish_reason", None) == "length"
    if truncated:
        # Truncated at the token cap — warn, don't silently cache a partial. (T-033)
        logger.warning(
            "Description for diagram %s was truncated at the %d-token cap "
            "(finish_reason=length); it may be cut mid-sentence.",
            region.path.name,
            MAX_TOKENS,
        )
    description_path.parent.mkdir(parents=True, exist_ok=True)
    description_path.write_text(text, encoding="utf-8")
    if truncated:
        truncation_marker(description_path).touch()  # keeps it out of the shared cache
    return text
