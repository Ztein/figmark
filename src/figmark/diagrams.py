"""Diagram extraction: one box per page-band of vector content (T-080).

Central-bank and similar agency reports embed vector charts (matplotlib exported
to PDF path commands) that page.get_images() does not catch. Earlier versions
tried to *classify* which drawing clusters are charts (solid-fill counts, cluster
gates) and silently dropped ~1 in 4 figures. The premise was wrong: only a vision
model can tell what a region is. So this module now unions a page's vector
content into one box per vertical band, splitting bands only where a body-text
paragraph sits between them, and lets the model decide what each box is
(T-081's structured is_figure decision skips the non-figures).
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

# Cheap early-exit for pure-text pages only. Kept deliberately low: the code does
# NOT judge whether a region is a chart — it captures any drawing cluster and lets
# the vision model + significance gate decide (T-080). A real figure page has far
# more than this; the size/cluster floors below do the actual noise filtering.
MIN_DRAWINGS_PER_PAGE = 5
# Drawings below this pixel size in BOTH dimensions do not count (specks).
# A drawing below it in exactly ONE dimension is an axis-aligned hairline —
# LibreOffice/TikZ draw chart axes and gridlines as zero-thickness strokes
# (T-055). These count as ordinary cluster members: line charts are mostly
# hairlines, and the code no longer tries to tell a chart from a grid (T-080).
MIN_DRAWING_DIM = 2
# Drawings larger than X% of the page area are skipped (background boxes)
MAX_DRAWING_AREA_RATIO = 0.4
# A drawing spanning nearly a full page dimension is page furniture (margin
# rules, section frames, header-to-footer borders), not figure content — and
# because banding is vertical-overlap based, one full-height margin rule would
# bridge every band on the page into a single full-page box (seen on ruled
# table pages: a 5 px margin bar unioned the page). No corpus figure spans
# edge to edge; coverage stays 100 % on the T-080 bench with this filter.
MAX_DRAWING_SPAN_RATIO = 0.9
# A text block is a *body paragraph* (not figure furniture — captions, source
# lines, axis notes) at this many words and lines. Bench on BoC MPR 2024-10 +
# BoJ Outlook 2024-10 + BIS AR 2024 (T-080): furniture and body word counts
# overlap heavily (BIS panel-title rows run 15–44 words), so no clean threshold
# exists — 20 words / 2 lines is the point where caption coverage stays 100 %
# on all three docs while region counts stay bounded (34/56/81). Used for two
# decisions: a paragraph between two visual bands splits them, and a paragraph
# inside a region is never suppressed from the body text (see
# ``text_block_in_region``).
PARA_MIN_WORDS = 20
PARA_MIN_LINES = 2
# A gap block must lie at least this fraction inside the gap to count as
# *between* the bands (rather than belonging to one of them).
GAP_CONTAINMENT = 0.7
# A drawing mostly inside a table-like find_tables candidate is the table
# path's content, not visual-band material — ruled/zebra tables draw row fills
# exactly like chart bars, and T-031's table path owns them. "Table-like" is
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
# Size floor: a band smaller than this (px) is stray marks (rules, decorations),
# not a renderable figure.
MIN_CLUSTER_WIDTH = 80
MIN_CLUSTER_HEIGHT = 60
# Extra px around the band bbox before text expansion
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


def _is_paragraph(text: str, n_lines: int | None = None) -> bool:
    """Body paragraph vs figure furniture (caption/source line/axis note) —
    the bench-validated word/line floor (see PARA_MIN_WORDS). Prose always
    carries sentence punctuation; tick-label runs ("RO CL MX …", "23 22 21 …")
    can exceed the word floor but never do — measured junk leakage drops from
    107 to ~0 words on BIS AR 2024 with this test. ``n_lines`` is checked only
    when the caller has it (page dicts do; pipeline TextBlocks don't)."""
    if len(text.split()) < PARA_MIN_WORDS:
        return False
    if n_lines is not None and n_lines < PARA_MIN_LINES:
        return False
    return "." in text or "," in text


def _page_text_blocks(page: fitz.Page) -> list[tuple[fitz.Rect, str, int]]:
    """(bbox, text, line count) for every non-empty text block on the page."""
    out: list[tuple[fitz.Rect, str, int]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        tb = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
        if tb.width <= 0 or tb.height <= 0:
            continue
        text = " ".join(
            span["text"] for line in block.get("lines", []) for span in line.get("spans", [])
        ).strip()
        if text:
            out.append((tb, text, len(block.get("lines", []))))
    return out


def _vertical_bands(rects: list[fitz.Rect]) -> list[list[fitz.Rect]]:
    """Maximal runs of vertically overlapping/touching drawings.

    No gap threshold: any vertical whitespace is a *potential* split point, but
    a split only happens when a body paragraph sits in the gap (see caller).
    """
    by_y = sorted(rects, key=lambda r: r.y0)
    bands: list[list[fitz.Rect]] = [[by_y[0]]]
    y_max = by_y[0].y1
    for r in by_y[1:]:
        if r.y0 <= y_max:
            bands[-1].append(r)
        else:
            bands.append([r])
        y_max = max(y_max, r.y1)
    return bands


def _union(rects: list[fitz.Rect]) -> fitz.Rect:
    box = fitz.Rect(rects[0])
    for r in rects[1:]:
        box |= r
    return box


def _paragraph_in_gap(
    blocks: list[tuple[fitz.Rect, str, int]], y_top: float, y_bot: float
) -> bool:
    """True if a body paragraph lies (mostly) between y_top and y_bot —
    the signal that two visual bands are separate figures, not one."""
    for tb, text, n_lines in blocks:
        inside = min(tb.y1, y_bot) - max(tb.y0, y_top)
        if inside / tb.height >= GAP_CONTAINMENT and _is_paragraph(text, n_lines):
            return True
    return False


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
    """Find visual regions on a page — one box per band of vector content.

    Pipeline: filter drawings (specks, background) → drop table-owned drawings →
    group into vertical bands, splitting only where a body paragraph sits between
    two bands → union each band, expand with neighbouring text → return sorted in
    reading order. No chart/not-chart judgement happens here: the vision model
    decides what each box is (T-080/T-081).
    """
    drawings = page.get_drawings()
    if len(drawings) < MIN_DRAWINGS_PER_PAGE:
        return []

    page_area = page.rect.width * page.rect.height
    max_drawing_area = MAX_DRAWING_AREA_RATIO * page_area

    rects: list[fitz.Rect] = []
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
        if (
            r.height >= MAX_DRAWING_SPAN_RATIO * page.rect.height
            or r.width >= MAX_DRAWING_SPAN_RATIO * page.rect.width
        ):
            continue  # page furniture (margin rule/border) — would bridge all bands
        # Axis-aligned hairlines (LO/TikZ axes, gridlines) are ordinary band
        # members (T-055).
        rects.append(fitz.Rect(r))
        sloped.append(_has_sloped_content(d))

    if not rects:
        return []

    # A drawing on a real data table is the table path's business (T-031/T-055)
    # — zebra row fills draw exactly like chart bars, and describing a table as
    # a picture double-represents it. Dropped *before* banding so table rows
    # cannot bridge two genuine figures into one band.
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
        before = len(rects)
        rects = [
            r
            for r in rects
            if not any(
                (r & s).get_area() >= TABLE_SUPPRESS_MIN_OVERLAP * max(r.get_area(), 1e-9)
                for s in suppressors
            )
        ]
        if len(rects) < before:
            logger.info(
                "page %d: %d drawing(s) on a data table left to the table path",
                page_num,
                before - len(rects),
            )
    if not rects:
        return []

    # Band the remaining drawings vertically; merge adjacent bands unless a body
    # paragraph sits in the gap — the only non-arbitrary "these are separate
    # figures" signal (T-080). Captions/source lines between two charts do NOT
    # split: they belong to the figure and land inside the rendered box.
    text_blocks = _page_text_blocks(page)
    bands = _vertical_bands(rects)
    merged: list[list[fitz.Rect]] = [bands[0]]
    for band in bands[1:]:
        gap_top = _union(merged[-1]).y1
        gap_bot = _union(band).y0
        if _paragraph_in_gap(text_blocks, gap_top, gap_bot):
            merged.append(band)
        else:
            merged[-1].extend(band)

    raw_bboxes: list[tuple[fitz.Rect, int]] = []
    for band in merged:
        box = _union(band)
        if box.width < MIN_CLUSTER_WIDTH or box.height < MIN_CLUSTER_HEIGHT:
            continue  # stray marks (rules, decorations) — below the size floor
        bbox = fitz.Rect(
            max(0, box.x0 - PADDING),
            max(0, box.y0 - PADDING),
            min(page.rect.width, box.x1 + PADDING),
            min(page.rect.height, box.y1 + PADDING),
        )
        raw_bboxes.append((bbox, len(band)))

    regions: list[DiagramRegion] = []
    for i, (bbox, n_draw) in enumerate(raw_bboxes):
        # Text expansion stops at the neighbouring band so two figures never
        # merge through a shared caption.
        y_min_limit = 0.0
        y_max_limit = page.rect.height
        for j, (other, _) in enumerate(raw_bboxes):
            if j == i:
                continue
            if other.y1 <= bbox.y0:
                y_min_limit = max(y_min_limit, other.y1 + 4)
            elif other.y0 >= bbox.y1:
                y_max_limit = min(y_max_limit, other.y0 - 4)

        expanded = _expand_with_neighboring_text(
            page, bbox, TEXT_EXPAND_DISTANCE, y_min_limit, y_max_limit
        )
        expanded &= page.rect
        # Bands can lie (partly) outside the page — crop marks, spill-over
        # content with negative coordinates. After clipping to the page, a
        # degenerate or tiny remnant is not a figure: rendering it crashes the
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
    bbox,
    regions: list[DiagramRegion],
    min_overlap: float = TEXT_IN_REGION_OVERLAP,
    text: str | None = None,
) -> bool:
    """True if a text block lies mostly inside a diagram region — its content is the
    diagram's internal labels, which leak into the body otherwise. (T-008)

    A body *paragraph* is never claimed, even when fully inside a region: with
    one-box-per-page bands (T-080), a box can legitimately cover flowing text
    (column layouts, bridged bands — measured 29/156/538 swallowed paragraph-words
    on BoC/BoJ/BIS even with per-band boxes). Keeping the paragraph in the body
    costs mild duplication with the rendered image; deleting it silently loses
    content — and figmark never silently degrades.
    """
    if text is not None and _is_paragraph(text):
        return False
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
