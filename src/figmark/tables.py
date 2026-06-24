"""Detect ruled data tables and turn them into TableBlocks.

PyMuPDF's ``page.find_tables()`` finds candidate tables, but on chart-heavy
documents it also latches onto chart gridlines and axis ladders, and on prose it
chops paragraphs into cells. A labelled bench (T-030, scripts/table_bench/) showed
that PyMuPDF + the conservative filter below reaches 100 % detection / 99 %
cell-recall on real tables while staying silent on chart pages — beating
pdfplumber without a new dependency. This module is the productionised filter.

The three gates, in order:
  1. drop a candidate that overlaps a detected diagram region (chart gridlines),
  2. require a numeric body (≥ MIN_ROWS rows and ≥ 2 numeric columns) — drops
     chart-caption strips,
  3. require a text label column — drops single-/double-column axis ladders.
A page whose candidates all fail falls back to today's text path (no table emitted).
"""

from __future__ import annotations

import logging
import re

import fitz

from .diagrams import find_diagram_regions
from .pdf_loader import TableBlock

logger = logging.getLogger("figmark.tables")

# Filter thresholds — calibrated on the labelled bench (T-030).
MIN_ROWS = 3
MIN_COLS = 2
# A column is "numeric" if ≥ this fraction of its non-empty cells are numbers;
# a "label" column if ≤ LABEL_COL_FRAC are.
NUMERIC_COL_FRAC = 0.6
LABEL_COL_FRAC = 0.4
# Drop a candidate table overlapping a detected diagram region by more than this.
DIAGRAM_OVERLAP = 0.5

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _norm(s: str | None) -> str:
    return (s or "").replace("−", "-").replace("–", "-").replace("—", "-")


def _is_num_cell(cell: str | None) -> bool:
    s = _norm(cell).strip()
    if not s:
        return False
    letters = sum(c.isalpha() for c in s)
    return bool(_NUM.search(s)) and letters <= 2


def _dims(grid: list[list[str]]) -> tuple[int, int]:
    return len(grid), max((len(r) for r in grid), default=0)


def _col_roles(grid: list[list[str]]) -> tuple[int, int]:
    """Return (#numeric columns, #label columns) over columns with ≥2 filled cells."""
    ncols = max((len(r) for r in grid), default=0)
    numeric = label = 0
    for c in range(ncols):
        col = [row[c] for row in grid if c < len(row)]
        nonempty = [x for x in col if _norm(x).strip()]
        if len(nonempty) < 2:
            continue
        frac = sum(_is_num_cell(x) for x in nonempty) / len(nonempty)
        if frac >= NUMERIC_COL_FRAC:
            numeric += 1
        elif frac <= LABEL_COL_FRAC:
            label += 1
    return numeric, label


def _overlaps_diagram(bbox, diagram_rects: list[fitz.Rect]) -> bool:
    a = fitz.Rect(bbox)
    if a.is_empty:
        return False
    area = abs(a.width * a.height)
    for d in diagram_rects:
        inter = a & d
        if not inter.is_empty and abs(inter.width * inter.height) / area > DIAGRAM_OVERLAP:
            return True
    return False


def keep_table(grid: list[list[str]], bbox, diagram_rects: list[fitz.Rect]) -> bool:
    """The 3-gate conservative filter (T-031). True = a real data table to emit."""
    nrows, ncols = _dims(grid)
    if nrows < MIN_ROWS or ncols < MIN_COLS:
        return False
    if _overlaps_diagram(bbox, diagram_rects):
        return False
    numeric, label = _col_roles(grid)
    if numeric < 2:  # no numeric body → chart caption / prose
        return False
    if label < 1:  # no text label column → axis ladder
        return False
    return True


def text_block_consumed(bbox, tables: list[TableBlock], min_overlap: float = 0.5) -> bool:
    """True if a text block lies mostly inside a kept table — its text is part of
    the table's cells, so it must be dropped from the loose text flow (no
    duplication). (T-031)
    """
    r = fitz.Rect(bbox)
    area = abs(r.width * r.height)
    if area <= 0:
        return False
    for t in tables:
        inter = r & fitz.Rect(t.bbox)
        if not inter.is_empty and abs(inter.width * inter.height) / area >= min_overlap:
            return True
    return False


def _clean_grid(raw: list[list]) -> list[list[str]]:
    """Normalise extracted cells to strings (None → "", collapse internal newlines)."""
    return [[" ".join((c or "").split()) for c in row] for row in raw]


def find_table_blocks(page: fitz.Page, page_num: int) -> list[TableBlock]:
    """Detect data tables on a page and return them as TableBlocks (reading order).

    Computes its own diagram regions for the overlap gate, so it works regardless
    of whether diagram description is enabled. If find_tables raises on a page it is
    logged loudly (cf. T-024) and the page yields no tables — never swallowed.
    """
    try:
        finder = page.find_tables()
    except Exception as e:  # noqa: BLE001 — never let one page's quirk crash the run
        logger.warning("find_tables raised on page %d (%s); skipping tables there.", page_num, e)
        return []

    diagram_rects = [fitz.Rect(r.bbox) for r in find_diagram_regions(page, page_num)]
    blocks: list[TableBlock] = []
    for t in finder.tables:
        grid = _clean_grid(t.extract())
        if keep_table(grid, t.bbox, diagram_rects):
            blocks.append(TableBlock(bbox=tuple(t.bbox), rows=grid))
    blocks.sort(key=lambda b: (round(b.bbox[1] / 10), b.bbox[0]))
    return blocks
