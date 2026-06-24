"""T-026 bench probe: where are the *real* ruled tables in the eval corpus?

Runs PyMuPDF find_tables() over every eval PDF and, for each detected table,
records: rows x cols, non-empty-cell ratio, and whether it overlaps a detected
diagram region (a chart-gridline false positive). A "good" table clears a
non-empty ratio and a min rows/cols and does NOT sit on a diagram.

This is the bench-before-code step T-026 requires. No extraction code ships
from this — it only measures which documents are worth validating against.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from figmark.diagrams import find_diagram_regions  # noqa: E402

MIN_NONEMPTY_RATIO = 0.6
MIN_ROWS = 2
MIN_COLS = 2


def _rect(b) -> fitz.Rect:
    return fitz.Rect(b)


def _overlaps(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = a & b
    if inter.is_empty or a.is_empty:
        return 0.0
    return abs(inter.width * inter.height) / abs(a.width * a.height)


def probe_doc(path: Path) -> dict:
    doc = fitz.open(path)
    total = good = empty = on_diagram = tiny = 0
    good_pages: list[int] = []
    for pno, page in enumerate(doc, start=1):
        try:
            tabs = page.find_tables()
        except Exception as e:  # noqa: BLE001 — probe only, log and move on
            print(f"    ! {path.name} p{pno}: find_tables raised {e!r}")
            continue
        diagram_rects = [_rect(r.bbox) for r in find_diagram_regions(page, pno)]
        for t in tabs.tables:
            total += 1
            cells = t.extract()
            nrows = len(cells)
            ncols = max((len(r) for r in cells), default=0)
            flat = [c for row in cells for c in row]
            nonempty = sum(1 for c in flat if c and str(c).strip())
            ratio = nonempty / len(flat) if flat else 0.0
            trect = _rect(t.bbox)
            on_diag = any(_overlaps(trect, d) > 0.5 for d in diagram_rects)
            if nrows < MIN_ROWS or ncols < MIN_COLS:
                tiny += 1
            elif ratio < MIN_NONEMPTY_RATIO:
                empty += 1
            elif on_diag:
                on_diagram += 1
            else:
                good += 1
                if pno not in good_pages:
                    good_pages.append(pno)
    doc.close()
    return {
        "name": path.name,
        "pages": len(fitz.open(path)) if False else None,
        "total": total,
        "good": good,
        "empty": empty,
        "on_diagram": on_diagram,
        "tiny": tiny,
        "good_pages": good_pages[:12],
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    targets = sorted((root / "examples" / "eval").glob("*.pdf"))
    extra = root / "examples" / "paper.pdf"
    if extra.exists():
        targets.append(extra)
    print(f"Probing {len(targets)} PDFs "
          f"(good = >={MIN_NONEMPTY_RATIO:.0%} non-empty cells, "
          f">={MIN_ROWS}x{MIN_COLS}, not on a diagram)\n")
    rows = []
    for p in targets:
        r = probe_doc(p)
        rows.append(r)
        flag = "  <== TABLE-RICH" if r["good"] >= 5 else ""
        print(f"{r['name']:<34} total={r['total']:>4}  good={r['good']:>4}  "
              f"empty={r['empty']:>4}  on_diag={r['on_diagram']:>3}  "
              f"tiny={r['tiny']:>3}{flag}")
        if r["good"]:
            print(f"    good pages: {r['good_pages']}")
    rows.sort(key=lambda r: r["good"], reverse=True)
    print("\nTop candidates for the labelled table bench:")
    for r in rows[:6]:
        if r["good"]:
            print(f"  {r['name']:<34} {r['good']} good tables, "
                  f"pages {r['good_pages']}")


if __name__ == "__main__":
    main()
