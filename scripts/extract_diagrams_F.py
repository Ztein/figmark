"""Approach F: PyMuPDF drawing-clustering.

Identifiera diagram-regioner i en PDF genom att klustra page.get_drawings() via
spatial proximity. Skriver ut varje hittad region som PNG för manuell inspektion.

Användning:
    .venv/bin/python -m scripts.extract_diagrams_F path/to/file.pdf [--pages 10,11,68]

Output:
    output/<pdf-stem>/diagram_F/page-NNN/region-NN.png
    output/<pdf-stem>/diagram_F/summary.txt
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import fitz


# --- Tröskel/parameter-konstanter (kan flyttas till config senare) -------------

MIN_DRAWING_DIM = 2          # ignorera drawings smaller än så här (decoration)
MAX_DRAWING_AREA_RATIO = 0.4 # ignorera drawings större än X% av sidan (bakgrunds-/ramrektanglar
                             # som annars länkar samman alla diagram via clustering)
MERGE_DISTANCE = 3           # pixels — drawings inom detta avstånd anses tillhöra samma kluster
                             # Lågt värde undviker att två separata diagram chain:as via närliggande drawings
MIN_DRAWINGS_PER_CLUSTER = 8 # ett kluster måste ha minst så här många primitiv för att räknas
MIN_CLUSTER_WIDTH = 80       # ignorera kluster smalare än så här (linjer, tabellramar)
MIN_CLUSTER_HEIGHT = 60      # ignorera kluster lägre än så här
INTERNAL_Y_GAP_SPLIT = 40    # om kluster har intern y-lucka större än så här, dela det (separerar staplade diagram)
PADDING = 6                  # px att inflatera bboxen med innan text-expansion
TEXT_EXPAND_DISTANCE = 30    # px — text-block inom så här långt över/under diagrammet inkluderas
RENDER_DPI = 200


@dataclass
class DiagramRegion:
    page_num: int  # 1-indexerat
    index: int     # 1-indexerat per sida
    bbox: fitz.Rect
    n_drawings: int


def _close(r1: fitz.Rect, r2: fitz.Rect, slack: float) -> bool:
    """Två bboxar 'närliggande' om de överlappar eller är inom `slack` pixels."""
    return not (
        r1.x1 + slack < r2.x0
        or r2.x1 + slack < r1.x0
        or r1.y1 + slack < r2.y0
        or r2.y1 + slack < r1.y0
    )


def _split_by_y_gap(group_rects: list[fitz.Rect], min_gap: float) -> list[list[fitz.Rect]]:
    """Dela ett kluster om det har en intern y-lucka större än min_gap.

    Typfall: Diagram 41 och 42 hamnar i samma drawing-kluster eftersom proximity-chain
    går genom gridlines. Men det finns en tydlig vertikal gap mellan dem (~100 px) som
    motsvarar Anm-text + Diagram 42-rubrik.
    """
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


def _cluster_rects(rects: list[fitz.Rect], merge_distance: float) -> list[list[int]]:
    """Union-find clustering av rektanglar via spatial proximity. Returnerar grupper av index."""
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

    # O(n²) — för ~hundra-tals drawings per sida är det OK
    for i in range(n):
        for j in range(i + 1, n):
            if _close(rects[i], rects[j], merge_distance):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _expand_with_neighboring_text(
    page: fitz.Page,
    bbox: fitz.Rect,
    max_distance: float,
    y_min_limit: float,
    y_max_limit: float,
) -> fitz.Rect:
    """Utöka bbox vertikalt för att inkludera närliggande text-block.

    Begränsas av y_min_limit (uppåt) och y_max_limit (nedåt) — typiskt sätta
    till föregående respektive nästa cluster-bbox så två diagram inte smälter
    ihop genom mellanliggande text (rubrik till nästa diagram etc.).
    """
    expanded = fitz.Rect(bbox)
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        tb = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
        if tb.width == 0 or tb.height == 0:
            continue
        # Måste överlappa horisontellt med diagram-bboxen (annars är det vid sidan)
        horiz_overlap = min(bbox.x1, tb.x1) - max(bbox.x0, tb.x0)
        if horiz_overlap < 0.3 * tb.width:
            continue
        # Ovanför diagrammet, men inte över y_min_limit
        if tb.y1 <= bbox.y0 and bbox.y0 - tb.y1 <= max_distance and tb.y0 >= y_min_limit:
            expanded |= tb
        # Under diagrammet, men inte under y_max_limit
        elif tb.y0 >= bbox.y1 and tb.y0 - bbox.y1 <= max_distance and tb.y1 <= y_max_limit:
            expanded |= tb
    return expanded


def find_diagram_regions(page: fitz.Page, page_num: int) -> list[DiagramRegion]:
    drawings = page.get_drawings()
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
            continue  # sidbakgrund/ram — ignorera
        rects.append(fitz.Rect(r))

    if not rects:
        return []

    groups = _cluster_rects(rects, MERGE_DISTANCE)

    # Steg 1: raw cluster-bboxar — efter clustering OCH y-gap split
    raw_bboxes: list[tuple[fitz.Rect, int]] = []
    for group in groups:
        if len(group) < MIN_DRAWINGS_PER_CLUSTER:
            continue
        cluster_rects = [rects[i] for i in group]
        # Dela klustret om det har stora interna y-gaps (staplade diagram)
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

    # Steg 2: text-expansion, begränsad av andra cluster-bboxar i samma kolumn
    raw_bboxes.sort(key=lambda b: b[0].y0)
    regions: list[DiagramRegion] = []
    for i, (bbox, n_draw) in enumerate(raw_bboxes):
        # Hitta y-gränser från andra clusters som ligger i samma horisontella kolumn
        y_min_limit = 0.0
        y_max_limit = page.rect.height
        for j, (other, _) in enumerate(raw_bboxes):
            if j == i:
                continue
            # Andra clustret måste överlappa horisontellt för att räknas som "spärr"
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
                bbox=expanded,
                n_drawings=n_draw,
            )
        )

    # Slutsortering i läsordning (y0, x0) — efter expansion kan ordningen ha skiftats
    regions.sort(key=lambda r: (round(r.bbox.y0 / 10), r.bbox.x0))
    for i, r in enumerate(regions, start=1):
        r.index = i
    return regions


def render_region(page: fitz.Page, bbox: fitz.Rect, dpi: int = RENDER_DPI) -> bytes:
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=matrix, clip=bbox, alpha=False)
    return pix.tobytes("png")


def parse_pages_arg(arg: str | None, total: int) -> list[int]:
    if not arg:
        return list(range(1, total + 1))
    parts = []
    for chunk in arg.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            a, b = chunk.split("-")
            parts.extend(range(int(a), int(b) + 1))
        else:
            parts.append(int(chunk))
    return [p for p in parts if 1 <= p <= total]


DIAGRAM_PROMPT = """Du ska syntolka ett diagram för användare som behöver beskrivande text.
Formulera svaret på myndighetssvenska — formellt, sakligt och tydligt, men begripligt för allmänheten.

Strukturera svaret så här:
1. **Vad diagrammet visar**: titel/ämne och vad x- respektive y-axeln mäter (inklusive enheter).
2. **Vilka serier/data**: nämn alla serier som visas (linjer, staplar, etc.) och hur de skiljs åt visuellt.
3. **De viktigaste observationerna**: trender, toppar, bottnar, brytpunkter, divergenser. Var konkret med siffror och årtal.
4. **Eventuella anmärkningar och källor** om de finns med i bilden.

Hitta inte på siffror. Om något är otydligt, skriv det."""


def describe_region(client, image_path: Path, model: str, max_tokens: int) -> str:
    """Skicka en region-bild till Gemma med diagram-prompt."""
    import base64
    img_bytes = image_path.read_bytes()
    data_uri = "data:image/png;base64," + base64.b64encode(img_bytes).decode("ascii")
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": DIAGRAM_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    )
    return (response.choices[0].message.content or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Extrahera diagram via PyMuPDF-drawings-clustering")
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--pages", type=str, default=None,
        help="Komma-separerade sidnummer eller intervall, t.ex. '10,11,68-70'",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("output"),
        help="Output-rot (default: output/)",
    )
    parser.add_argument(
        "--describe", action="store_true",
        help="Skicka varje region till Gemma för syntolkning (kostar API-tokens)",
    )
    args = parser.parse_args()

    client = None
    cfg = None
    if args.describe:
        # Lazy import för att inte kräva config för bara extraction
        from src.config import load_config
        from src.describe import make_client
        cfg = load_config()
        client = make_client(cfg)
        print(f"Syntolkning aktiverad — modell: {cfg.api.model}\n")

    doc = fitz.open(args.pdf)
    pages_to_process = parse_pages_arg(args.pages, len(doc))

    out_dir = args.output / args.pdf.stem / "diagram_F"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_lines = [
        f"PDF: {args.pdf}",
        f"Sidor: {len(doc)} totalt, {len(pages_to_process)} behandlade",
        f"Parametrar: MERGE_DISTANCE={MERGE_DISTANCE}, MIN_DRAWINGS_PER_CLUSTER={MIN_DRAWINGS_PER_CLUSTER}, "
        f"MIN_CLUSTER={MIN_CLUSTER_WIDTH}x{MIN_CLUSTER_HEIGHT}, PADDING={PADDING}, DPI={RENDER_DPI}",
        "",
        "Sida | Drawings | Regioner | Sparade filer",
        "-----|----------|----------|---------------",
    ]

    total_regions = 0
    for page_num in pages_to_process:
        page = doc.load_page(page_num - 1)
        n_drawings = len(page.get_drawings())
        regions = find_diagram_regions(page, page_num)

        if regions:
            page_dir = out_dir / f"page-{page_num:03d}"
            page_dir.mkdir(parents=True, exist_ok=True)
            saved = []
            for region in regions:
                fname = f"region-{region.index:02d}.png"
                png_path = page_dir / fname
                png_path.write_bytes(render_region(page, region.bbox))
                saved.append(fname)
                if args.describe and client is not None and cfg is not None:
                    desc_path = png_path.with_suffix(".txt")
                    if desc_path.exists() and desc_path.read_text(encoding="utf-8").strip():
                        print(f"  sida {page_num} region {region.index}: cache")
                    else:
                        print(f"  sida {page_num} region {region.index}: → API")
                        text = describe_region(client, png_path, cfg.api.model, 800)
                        desc_path.write_text(text, encoding="utf-8")
            summary_lines.append(
                f"{page_num:>4} | {n_drawings:>8} | {len(regions):>8} | {', '.join(saved)}"
            )
        else:
            summary_lines.append(f"{page_num:>4} | {n_drawings:>8} | {0:>8} | -")

        total_regions += len(regions)

    summary_lines.append("")
    summary_lines.append(f"TOTALT: {total_regions} regioner extraherade")

    summary_path = out_dir / "summary.txt"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print("\n".join(summary_lines))
    print(f"\nSparat till: {out_dir}")
    print(f"Summary: {summary_path}")

    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
