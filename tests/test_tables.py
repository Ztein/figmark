"""Tests for table detection and the conservative filter (T-031, offline)."""

from __future__ import annotations

import logging
from pathlib import Path

import fitz
import pytest

from figmark.output import _markdown_table
from figmark.pdf_loader import TableBlock
from figmark.tables import find_table_blocks, keep_table, text_block_consumed

# A real data table: a text label column + several numeric columns.
_REAL = [
    ["", "2024", "2025", "2026"],
    ["US", "2.8", "1.9", "1.8"],
    ["Euro area", "0.8", "1.4", "1.2"],
    ["UK", "1.1", "1.4", "1.0"],
]
# A chart-caption strip: prose, no numeric body.
_CAPTION = [["a) Inflation and growth", "b) Real GDP", "c) Potential output"]]
# An axis-tick ladder: numeric columns but no text label column.
_LADDER = [["5", "2.5"], ["4", "2.0"], ["3", "1.5"], ["2", "1.0"], ["1", "0.5"]]


def test_keep_table_accepts_real_data_table():
    assert keep_table(_REAL, (0, 0, 300, 100), []) is True


def test_keep_table_rejects_chart_caption():
    assert keep_table(_CAPTION, (0, 0, 300, 30), []) is False


def test_keep_table_rejects_axis_ladder():
    assert keep_table(_LADDER, (0, 0, 60, 200), []) is False


def test_keep_table_rejects_table_over_diagram():
    """A grid that would otherwise pass is dropped if it sits on a diagram region."""
    diagram = fitz.Rect(0, 0, 300, 100)
    assert keep_table(_REAL, (10, 10, 290, 90), [diagram]) is False


def test_text_block_consumed_inside_table():
    table = TableBlock(bbox=(0, 0, 300, 100), rows=_REAL)
    assert text_block_consumed((10, 10, 280, 90), [table]) is True  # inside
    assert text_block_consumed((10, 200, 280, 230), [table]) is False  # below the table


def test_markdown_table_is_valid_github_markdown():
    md = _markdown_table(_REAL)
    lines = md.splitlines()
    assert lines[0] == "|  | 2024 | 2025 | 2026 |"
    assert lines[1] == "| --- | --- | --- | --- |"
    assert "| US | 2.8 | 1.9 | 1.8 |" in lines
    # every row has the same number of pipes → a parseable table
    assert len({line.count("|") for line in lines}) == 1


def test_markdown_table_escapes_pipes():
    md = _markdown_table([["a|b", "c"], ["1", "2"]])
    assert "a\\|b" in md


def test_find_table_blocks_extracts_real_table_offline():
    """On a Norges MPR page with a real forecast table, a TableBlock is produced —
    no API calls involved (pure PyMuPDF + filter). (T-031)"""
    pdf = Path("examples/eval/norges-mpr-4-2025.pdf")
    if not pdf.exists():
        pytest.skip("eval corpus not present")
    doc = fitz.open(pdf)
    try:
        blocks = find_table_blocks(doc[52], 53)  # p53: international projections table
        assert len(blocks) >= 1
        assert any(len(b.rows) >= 3 for b in blocks)
        # the data survives into a valid Markdown table
        md = _markdown_table(blocks[0].rows)
        assert md.count("\n") >= 3 and "---" in md
    finally:
        doc.close()


def test_find_table_blocks_silent_on_chart_page():
    """A vector-chart page (no ruled data tables) yields no tables. (T-031)"""
    pdf = Path("examples/eval/riksbank-ppr-202503.pdf")
    if not pdf.exists():
        pytest.skip("eval corpus not present")
    doc = fitz.open(pdf)
    try:
        assert find_table_blocks(doc[9], 10) == []
    finally:
        doc.close()


def test_find_tables_error_is_logged_not_swallowed(tmp_path: Path, caplog):
    """If find_tables raises on a page, it is logged loudly and the page yields no
    tables — never silently swallowed (cf. T-024)."""
    doc = fitz.open()
    page = doc.new_page()

    def boom():
        raise RuntimeError("table finder exploded")

    page.find_tables = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="figmark.tables"):
        blocks = find_table_blocks(page, 1)
    doc.close()

    assert blocks == []
    assert "find_tables raised" in caplog.text
