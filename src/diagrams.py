"""Diagram-extraktion via PyMuPDF drawing-clustering.

Riksbankens och liknande myndighetsrapporter har vektordiagram (matplotlib-export
till PDF path-commands) som inte fångas av page.get_images(). Den här modulen
hittar diagram-regioner genom att klustra drawings spatialt och expanderar bbox:en
för att fånga axel-titlar och källrader.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import fitz

from .config import Config
from .context import ContextText

# ============================================================================
# Tekniska konstanter för clustering-pipelinen. Tuna här om en specifik
# PDF-typ kräver det. Empiriskt utprovade mot Riksbankens penningpolitiska
# rapport (vektordiagram från matplotlib).
# ============================================================================

# Sidor med färre drawings än så här undersöks inte (text-tunga sidor)
MIN_DRAWINGS_PER_PAGE = 30
# Drawings under denna pixelstorlek räknas inte (dekoration)
MIN_DRAWING_DIM = 2
# Drawings större än X% av sidans yta hoppas över (bakgrundsrutor)
MAX_DRAWING_AREA_RATIO = 0.4
# Drawings inom denna pixel-distans kopplas till samma kluster
MERGE_DISTANCE = 3
# Ett kluster måste ha minst så här många drawings
MIN_DRAWINGS_PER_CLUSTER = 8
# Kluster måste vara minst så här stora (px)
MIN_CLUSTER_WIDTH = 80
MIN_CLUSTER_HEIGHT = 60
# Interna y-luckor större än så här delar klustret (staplade diagram)
INTERNAL_Y_GAP_SPLIT = 40
# Extra px runt clustering-bboxen innan text-expansion
PADDING = 6
# Närliggande text-block (axel-titel/källrad) inom så här px inkluderas
TEXT_EXPAND_DISTANCE = 30
# DPI för rendering till diagram-bilden som skickas till Gemma
RENDER_DPI = 200
# Tak för diagram-syntolkning
MAX_TOKENS = 1200
# Inklippningsmall i full_text.txt
PLACEHOLDER = "[Diagram: {description}]"


@dataclass
class DiagramRegion:
    page_num: int     # 1-indexerat
    index: int        # 1-indexerat per sida
    bbox: tuple[float, float, float, float]
    n_drawings: int
    path: Path | None = None  # fylls i när bilden sparas


def _close(r1: fitz.Rect, r2: fitz.Rect, slack: float) -> bool:
    return not (
        r1.x1 + slack < r2.x0
        or r2.x1 + slack < r1.x0
        or r1.y1 + slack < r2.y0
        or r2.y1 + slack < r1.y0
    )


def _cluster_rects(rects: list[fitz.Rect], merge_distance: float) -> list[list[int]]:
    """Union-find clustering av rektanglar via spatial proximity."""
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

    for i in range(n):
        for j in range(i + 1, n):
            if _close(rects[i], rects[j], merge_distance):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _split_by_y_gap(group_rects: list[fitz.Rect], min_gap: float) -> list[list[fitz.Rect]]:
    """Dela ett kluster om det har en intern y-lucka större än min_gap."""
    if len(group_rects) < 2:
        return [group_rects]
    by_y = sorted(group_rects, key=lambda r: r.y0)
    splits: list[list[fitz.Rect]] = []
    current = [by_y[0]]
    current_max_y = by_y[0].y1
    for r in by_y[1:]:
        gap = r.y0 - current_max_y
        if gap > min_gap:
            splits.append(current)
            current = [r]
            current_max_y = r.y1
        else:
            current.append(r)
            current_max_y = max(current_max_y, r.y1)
    splits.append(current)
    return splits


def _expand_with_neighboring_text(
    page: fitz.Page,
    bbox: fitz.Rect,
    max_distance: float,
    y_min_limit: float,
    y_max_limit: float,
) -> fitz.Rect:
    """Utöka bbox vertikalt för att inkludera närliggande text-block.

    Begränsas av y_min/max_limit så två diagram inte smälter ihop.
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
    """Hitta diagram-regioner på en sida.

    Pipeline: filter drawings → cluster spatialt → splita på intern y-gap →
    expandera bbox med närliggande text → returnera sorterat i läsordning.
    """
    drawings = page.get_drawings()
    if len(drawings) < MIN_DRAWINGS_PER_PAGE:
        return []

    page_area = page.rect.width * page.rect.height
    max_drawing_area = MAX_DRAWING_AREA_RATIO * page_area

    rects: list[fitz.Rect] = []
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        if r.width < MIN_DRAWING_DIM or r.height < MIN_DRAWING_DIM:
            continue
        if r.width * r.height > max_drawing_area:
            continue  # sidbakgrund/ram
        rects.append(fitz.Rect(r))

    if not rects:
        return []

    groups = _cluster_rects(rects, MERGE_DISTANCE)

    raw_bboxes: list[tuple[fitz.Rect, int]] = []
    for group in groups:
        if len(group) < MIN_DRAWINGS_PER_CLUSTER:
            continue
        cluster_rects = [rects[i] for i in group]
        for sub in _split_by_y_gap(cluster_rects, INTERNAL_Y_GAP_SPLIT):
            if len(sub) < MIN_DRAWINGS_PER_CLUSTER:
                continue
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


def render_and_save_region(
    page: fitz.Page,
    region: DiagramRegion,
    out_dir: Path,
) -> Path:
    """Rendera region-bboxen som PNG, returnera path."""
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
) -> str:
    """Skicka diagram-bilden till Gemma med diagram-specifik prompt.

    Cache: om description_path finns och är icke-tom, läs från disk.
    Om context ges läggs den in före uppgiften i prompten.
    """
    if description_path.exists():
        cached = description_path.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    if region.path is None:
        raise RuntimeError(f"Region {region.page_num}.{region.index} har ingen sparad path")

    img_bytes = region.path.read_bytes()
    data_uri = "data:image/png;base64," + base64.b64encode(img_bytes).decode("ascii")

    # Bygg user-text med eventuell kontext
    if context is not None and not context.is_empty():
        user_text = f"{context.format_for_prompt()}\n\n[Uppgift]\n{cfg.diagrams.prompt}"
    else:
        user_text = cfg.diagrams.prompt

    response = client.chat.completions.create(
        model=cfg.api.model,
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
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError(
            f"API returnerade tomt innehåll för diagram {region.path.name} "
            f"(modell={cfg.api.model})."
        )
    description_path.parent.mkdir(parents=True, exist_ok=True)
    description_path.write_text(text, encoding="utf-8")
    return text
