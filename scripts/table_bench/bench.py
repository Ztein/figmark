"""T-030 labelled table bench.

Scores table extraction against hand-labelled ground truth so the
PyMuPDF-vs-pdfplumber decision (T-026 / T-031) rests on numbers, not on raw
find_tables() counts — which the probe already showed are misleading.

Ground truth was transcribed by hand from high-DPI renders of each page
(see scripts/probe_tables.py for how the candidate pages were found). It is
NOT derived from any extractor, so the bench is not circular.

Metrics per real table:
  - detection : did the filter keep a table on that page? (binary)
  - shape     : do the kept table's rows x cols match ground truth? (binary)
  - cells     : precision / recall over the multiset of numeric tokens
                (the data payload — robust to label-text and row/col offsets)
  - renders   : does the kept grid form a rectangular Markdown table?

Negative controls (chart captions, axis ladders, vector-chart pages) must yield
ZERO kept tables — that is what stops garbage from being injected.

Run:  python scripts/table_bench/bench.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
from figmark.diagrams import find_diagram_regions  # noqa: E402

EVAL = ROOT / "examples" / "eval"

# ---------------------------------------------------------------------------
# Ground truth — hand-transcribed from hi-DPI renders. One entry per (doc, page).
# Grids include the header row(s); section-header rows (e.g. "Assets") carry the
# label only. "" is an empty cell.
# ---------------------------------------------------------------------------

GROUND_TRUTH = {
    ("boc-mpr-202401.pdf", 14): {  # Table 2: contributions to real GDP growth
        "title": "BoC Table 2 — contributions to GDP growth",
        "grid": [
            ["", "2022", "2023", "2024", "2025"],
            ["Consumption", "2.7 (2.5)", "1.2 (1.3)", "0.3 (0.4)", "0.9 (0.9)"],
            ["Housing", "-1.2 (-1.1)", "-0.9 (-1.1)", "0.4 (0.2)", "0.5 (0.7)"],
            ["Government", "0.8 (0.5)", "0.5 (0.3)", "0.6 (0.6)", "0.5 (0.5)"],
            ["Business fixed investment", "0.5 (0.7)", "0.1 (0.2)", "-0.1 (0.0)", "0.3 (0.5)"],
            ["Subtotal: final domestic demand", "2.8 (2.6)", "0.9 (0.7)", "1.2 (1.2)", "2.2 (2.6)"],
            ["Exports", "1.0 (0.9)", "1.6 (1.6)", "0.3 (0.3)", "1.3 (0.8)"],
            ["Imports", "-2.4 (-2.4)", "-0.3 (-0.4)", "-0.1 (-0.6)", "-0.9 (-0.8)"],
            ["Inventories", "2.4 (2.3)", "-1.2 (-1.5)", "-0.6 (0.0)", "-0.2 (-0.1)"],
            ["GDP", "3.8 (3.4)", "1.0 (1.2)", "0.8 (0.9)", "2.4 (2.5)"],
        ],
    },
    ("boc-mpr-202401.pdf", 6): {  # Table 1: projection for global growth
        "title": "BoC Table 1 — global growth projection",
        "grid": [
            ["", "Share of real global GDP (%)", "2022", "2023", "2024", "2025"],
            ["United States", "16", "1.9 (1.9)", "2.5 (2.2)", "1.7 (0.8)", "1.2 (1.2)"],
            ["Euro area", "12", "3.4 (3.4)", "0.4 (0.5)", "0.5 (0.7)", "1.6 (1.5)"],
            ["Japan", "4", "0.9 (1.0)", "2.0 (2.0)", "0.7 (0.8)", "1.1 (0.9)"],
            ["China", "18", "3.0 (3.0)", "5.2 (5.1)", "4.5 (4.5)", "4.5 (4.4)"],
            ["Oil-importing EMEs", "34", "4.5 (4.5)", "3.7 (3.6)", "3.1 (3.0)", "3.6 (3.4)"],
            ["Rest of the world", "16", "3.5 (3.5)", "1.2 (1.7)", "1.5 (1.4)", "1.5 (1.3)"],
            ["World", "100", "3.4 (3.4)", "3.0 (2.9)", "2.5 (2.3)", "2.7 (2.6)"],
        ],
    },
    ("fed-mpr-202407.pdf", 53): {  # Federal Reserve balance sheet
        "title": "Fed — balance-sheet comparison",
        "grid": [
            [
                "",
                "June 19, 2024",
                "February 28, 2024",
                "Change (since February 2024)",
                "Memo: Change (since June 1, 2022)",
            ],
            ["Assets", "", "", "", ""],
            ["Total securities", "", "", "", ""],
            ["Treasury securities", "4453", "4661", "-208", "-1318"],
            ["Agency debt and MBS", "2357", "2406", "-49", "-353"],
            ["Unamortized premiums", "265", "274", "-8", "-72"],
            ["Repurchase agreements", "0", "0", "0", "0"],
            ["Loans and lending facilities", "", "", "", ""],
            ["PPPLF", "3", "3", "0", "-17"],
            ["Discount window", "7", "2", "5", "6"],
            ["BTFP", "107", "163", "-56", "107"],
            ["Other loans and lending facilities", "11", "15", "-4", "-23"],
            ["Central bank liquidity swaps", "0", "0", "0", "0"],
            ["Other assets", "49", "44", "6", "7"],
            ["Total assets and capital", "7253", "7568", "-315", "-1663"],
            ["Liabilities", "", "", "", ""],
            ["Federal Reserve notes", "2301", "2282", "18", "70"],
            ["Reserves held by depository institutions", "3366", "3541", "-175", "9"],
            ["Reverse repurchase agreements", "", "", "", ""],
            ["Foreign official and international accounts", "389", "339", "50", "124"],
            ["Others", "376", "570", "-194", "-1589"],
            ["U.S. Treasury General Account", "782", "768", "14", "2"],
            ["Other deposits", "158", "162", "-4", "-90"],
            ["Other liabilities and capital", "-120", "-94", "-25", "-188"],
            ["Total liabilities and capital", "7253", "7568", "-315", "-1663"],
        ],
    },
    ("norges-mpr-4-2025.pdf", 53): {  # Table 1 international projections
        "title": "Norges-4 Table 1 — international projections",
        "grid": [
            ["", "Weights Percent", "2024", "2025", "2026", "2027", "2028"],
            ["GDP", "", "", "", "", "", ""],
            ["US", "12", "2.8 (0)", "1.9 (0.1)", "1.8 (0.2)", "1.7 (0)", "1.7 (0)"],
            ["Euro area", "47", "0.8 (0)", "1.4 (0.1)", "1.2 (0.1)", "1.3 (0)", "1.4 (0)"],
            ["UK", "15", "1.1 (0)", "1.4 (0.1)", "1 (-0.1)", "1.4 (0.1)", "1.2 (0.1)"],
            ["Sweden", "18", "0.9 (0.1)", "1.9 (0.7)", "2.3 (0.2)", "1.9 (-0.2)", "2.1 (0)"],
            ["China", "8", "5 (0.1)", "4.9 (0.1)", "4.4 (0.3)", "4.1 (0)", "3.8 (0)"],
            [
                "5 trading partners",
                "100",
                "1.5 (0.1)",
                "1.8 (0.2)",
                "1.7 (0.1)",
                "1.7 (-0.1)",
                "1.7 (0)",
            ],
            ["Prices", "", "", "", "", "", ""],
            ["Underlying inflation", "", "3 (0)", "2.7 (0.1)", "2.3 (0)", "2.1 (0)", "2.2 (0)"],
            ["Wage growth", "", "4.3 (-0.1)", "3.8 (0.3)", "3.3 (0.1)", "3.1 (0.1)", "2.9 (0)"],
            [
                "Prices for consumer goods imported to Norway",
                "",
                "2.7 (0)",
                "0.1 (0)",
                "0 (0)",
                "0.3 (-0.4)",
                "0.7 (-0.2)",
            ],
            [
                "Prices for intermediate goods imported to Norway",
                "",
                "0.1 (-0.1)",
                "0.5 (0)",
                "0.7 (-0.2)",
                "1.7 (0.2)",
                "1.8 (0.3)",
            ],
        ],
    },
    ("norges-mpr-2-2025.pdf", 63): {  # regression: same structure, earlier edition
        "title": "Norges-2 Table 1 — international projections (regression)",
        "grid": [
            ["", "Weights Percent", "2024", "2025", "2026", "2027", "2028"],
            ["GDP", "", "", "", "", "", ""],
            ["US", "12", "2.8 (0)", "1.6 (-0.3)", "1.4 (-0.3)", "1.8 (0)", "1.7 (0.1)"],
            ["Euro area", "47", "0.8 (0)", "1 (0.1)", "1.2 (-0.2)", "1.4 (-0.1)", "1.3 (-0.1)"],
            ["UK", "15", "1.1 (0.2)", "1.1 (0.1)", "1.1 (-0.4)", "1.3 (-0.1)", "1.2 (-0.1)"],
            ["Sweden", "18", "1 (0.1)", "1.3 (-0.5)", "2.2 (-0.1)", "2.1 (-0.1)", "2.1 (0.5)"],
            ["China", "8", "5 (0.1)", "4.5 (0)", "3.8 (0)", "4.1 (0.1)", "3.8 (0.1)"],
            [
                "5 trading partners",
                "100",
                "1.5 (0.1)",
                "1.4 (-0.5)",
                "1.6 (-0.2)",
                "1.8 (-0.1)",
                "1.7 (0.1)",
            ],
            ["Prices", "", "", "", "", "", ""],
            ["Underlying inflation", "", "3 (0)", "2.6 (0)", "2.3 (0.1)", "2.2 (0.1)", "2.1 (0)"],
            ["Wage growth", "", "4.4 (0)", "3.4 (0)", "3.2 (0)", "3 (0)", "2.9 (0)"],
            [
                "Prices for consumer goods imported to Norway",
                "",
                "2.7 (0)",
                "0.2 (-0.8)",
                "0.4 (0.2)",
                "0.7 (0)",
                "0.9 (0)",
            ],
            [
                "Prices for intermediate goods imported to Norway",
                "",
                "0.1 (0)",
                "0.7 (-1.1)",
                "0.8 (-0.9)",
                "1.5 (0)",
                "1.5 (0)",
            ],
        ],
    },
}

# Negative controls — these MUST yield zero kept tables.
CONTROLS = [
    ("ecb-fsr-202411.pdf", 6, "chart-caption row (a/b/c)"),
    ("bis-ar-2024.pdf", 31, "chart axis-tick ladder"),
    ("riksbank-ppr-202503.pdf", 10, "vector-chart page (no ruled tables)"),
]
# Whole-document control: the two docs whose raw find_tables counts were inflated.
CONTROL_DOCS = ["ecb-fsr-202411.pdf", "bis-ar-2024.pdf"]


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _norm(s: str | None) -> str:
    return (s or "").replace("−", "-").replace("–", "-").replace("—", "-")


def num_tokens(cell: str | None) -> list[str]:
    """Numeric tokens in a cell, comma-stripped. '2.8 (-0.1)' -> ['2.8','-0.1']."""
    return [t.replace(",", "") for t in _NUM.findall(_norm(cell))]


def is_num_cell(cell: str | None) -> bool:
    s = _norm(cell).strip()
    if not s:
        return False
    letters = sum(c.isalpha() for c in s)
    return bool(_NUM.search(s)) and letters <= 2


def grid_num_multiset(grid: list[list]) -> Counter:
    c: Counter = Counter()
    for row in grid:
        for cell in row:
            c.update(num_tokens(cell))
    return c


def dims(grid: list[list]) -> tuple[int, int]:
    return len(grid), max((len(r) for r in grid), default=0)


# ---------------------------------------------------------------------------
# The candidate filter (prototype of T-031's three gates). Tunable here.
# ---------------------------------------------------------------------------

MIN_ROWS = 3
MIN_COLS = 2
NUMERIC_COL_FRAC = 0.6
LABEL_COL_FRAC = 0.4
DIAGRAM_OVERLAP = 0.5


def _col_roles(grid: list[list]) -> tuple[int, int]:
    """Return (#numeric columns, #label columns)."""
    ncols = max((len(r) for r in grid), default=0)
    numeric = label = 0
    for c in range(ncols):
        col = [row[c] for row in grid if c < len(row)]
        nonempty = [x for x in col if _norm(x).strip()]
        if len(nonempty) < 2:
            continue
        frac = sum(is_num_cell(x) for x in nonempty) / len(nonempty)
        if frac >= NUMERIC_COL_FRAC:
            numeric += 1
        elif frac <= LABEL_COL_FRAC:
            label += 1
    return numeric, label


def _overlaps_diagram(bbox, diagram_rects) -> bool:
    a = fitz.Rect(bbox)
    if a.is_empty:
        return False
    for d in diagram_rects:
        inter = a & d
        if (
            not inter.is_empty
            and abs(inter.width * inter.height) / abs(a.width * a.height) > DIAGRAM_OVERLAP
        ):
            return True
    return False


def keep_table(grid, bbox, diagram_rects) -> tuple[bool, str]:
    nrows, ncols = dims(grid)
    if nrows < MIN_ROWS or ncols < MIN_COLS:
        return False, f"too small ({nrows}x{ncols})"
    if _overlaps_diagram(bbox, diagram_rects):
        return False, "overlaps a diagram region"
    numeric, label = _col_roles(grid)
    if numeric < 2:
        return False, f"no numeric body ({numeric} numeric cols)"
    if label < 1:
        return False, "no label column (axis ladder?)"
    return True, "kept"


def kept_tables_on_page(page, pno):
    """Run find_tables, apply the filter, return list of (grid, bbox) survivors."""
    try:
        tabs = page.find_tables()
    except Exception as e:  # noqa: BLE001
        print(f"    ! find_tables raised on p{pno}: {e!r}")
        return []
    diagram_rects = [fitz.Rect(r.bbox) for r in find_diagram_regions(page, pno)]
    out = []
    for t in tabs.tables:
        grid = t.extract()
        ok, _ = keep_table(grid, t.bbox, diagram_rects)
        if ok:
            out.append((grid, t.bbox))
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_against_gt(kept, gt_grid):
    """Recall = GT numeric tokens recovered across ALL kept tables on the page
    (the real output emits every kept table, so a table split into two parts by
    find_tables still delivers all its data). Shape is the best single-table match,
    reported for information — exact match is not required when GT is a labelled
    sub-region or the detector splits one table into several."""
    gt = grid_num_multiset(gt_grid)
    union: Counter = Counter()
    best_shape = (0, 0)
    best_overlap = -1
    renders_all = True
    for grid, _ in kept:
        ex = grid_num_multiset(grid)
        union += ex
        overlap = sum((ex & gt).values())
        if overlap > best_overlap:
            best_overlap = overlap
            best_shape = dims(grid)
        if len({len(r) for r in grid}) != 1:
            renders_all = False
    recovered = sum((union & gt).values())
    recall = recovered / max(sum(gt.values()), 1)
    return {"recall": recall, "shape": best_shape, "renders": renders_all}


def run_pymupdf():
    print("\n=== PyMuPDF find_tables() + 3-gate filter ===\n")
    det = renders_ok = 0
    rec_sum = 0.0
    n = len(GROUND_TRUTH)
    for (doc, pno), gt in GROUND_TRUTH.items():
        d = fitz.open(EVAL / doc)
        kept = kept_tables_on_page(d[pno - 1], pno)
        d.close()
        if not kept:
            print(f"  MISS  {gt['title']}  — filter kept 0 tables")
            continue
        det += 1
        s = score_against_gt(kept, gt["grid"])
        rec_sum += s["recall"]
        renders_ok += s["renders"]
        print(f"  OK    {gt['title']}")
        print(
            f"        cell-recall={s['recall']:.0%}  best-shape={s['shape']} (gt{dims(gt['grid'])})  "
            f"renders={'yes' if s['renders'] else 'NO'}  (kept {len(kept)} on page)"
        )
    print(
        f"\n  detection {det}/{n}   mean cell-recall {rec_sum / max(det, 1):.0%}   "
        f"renders {renders_ok}/{n}"
    )

    print("\n  -- negative controls (must keep 0) --")
    for doc, pno, why in CONTROLS:
        d = fitz.open(EVAL / doc)
        kept = kept_tables_on_page(d[pno - 1], pno)
        d.close()
        flag = "ok" if not kept else "*** LEAK ***"
        print(f"     {doc} p{pno} ({why}): kept {len(kept)}  {flag}")
    for doc in CONTROL_DOCS:
        d = fitz.open(EVAL / doc)
        leaks = [(i + 1, len(k)) for i, p in enumerate(d) if (k := kept_tables_on_page(p, i + 1))]
        total = sum(c for _, c in leaks)
        d.close()
        where = f" on pages {[p for p, _ in leaks]}" if leaks else ""
        print(f"     whole doc {doc}: kept {total}{where} (raw find_tables was much higher)")


def run_pdfplumber():
    try:
        import pdfplumber
    except ImportError:
        print("\n=== pdfplumber: not installed — skipping (bench-only comparator) ===")
        print("    install with `pip install pdfplumber` in the venv to run the comparison")
        return
    print("\n=== pdfplumber extract_tables() (raw, no diagram filter) ===\n")
    det = 0
    rec_sum = 0.0
    n = len(GROUND_TRUTH)
    for (doc, pno), gt in GROUND_TRUTH.items():
        with pdfplumber.open(EVAL / doc) as pdf:
            tables = pdf.pages[pno - 1].extract_tables() or []
        if not tables:
            print(f"  MISS  {gt['title']}  — extract_tables found 0")
            continue
        det += 1
        gt_ms = grid_num_multiset(gt["grid"])
        best = 0.0
        bestdims = (0, 0)
        for tb in tables:
            ex = grid_num_multiset(tb)
            inter = sum((ex & gt_ms).values())
            r = inter / max(sum(gt_ms.values()), 1)
            if r > best:
                best = r
                bestdims = dims(tb)
        rec_sum += best
        print(
            f"  OK    {gt['title']}  cells recall={best:.0%}  shape={bestdims} vs gt{dims(gt['grid'])}"
        )
    print(f"\n  detection {det}/{n}   mean cell-recall {rec_sum / max(det, 1):.0%}")
    print("\n  -- negative controls (raw, no filter) --")
    for doc in CONTROL_DOCS:
        with pdfplumber.open(EVAL / doc) as pdf:
            total = sum(len(p.extract_tables() or []) for p in pdf.pages)
        print(f"     whole doc {doc}: extract_tables returned {total} raw")


if __name__ == "__main__":
    run_pymupdf()
    run_pdfplumber()
