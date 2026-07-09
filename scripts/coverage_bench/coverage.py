#!/usr/bin/env python3
"""Figure-coverage metric: did figmark capture the figures the document declares?

Extraction-independent yardstick. Ground truth = the document's own numbered
figure captions ("Chart N", "Figure N", "Diagram N", ...). Captured = the
non-skipped figures in figmark's ``figures.json``. A figure number is *covered*
if figmark captured a figure on any page where that caption appears.

This is a deliberate LOWER BOUND on misses (page-level, and a cross-reference to
"Chart 5" on another page can over-credit) — so it never cries wolf. It measures
coverage, not description quality (that needs an LLM judge).

Usage:
    python scripts/coverage_bench/coverage.py DOC.pdf OUTPUT_DIR [DOC2.pdf OUTDIR2 ...]

Each OUTPUT_DIR is the figmark run dir containing <name>.figures.json.
Prints a per-document table + an aggregate line. Docs with < 2 figure captions
report N/A (no caption ground truth — e.g. an uncaptioned Word file).
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import fitz

# Caption words that denote an interpretable figure. "Table" is excluded on
# purpose — tables go through a different pipeline path, not the figure path.
FIGURE_WORDS = ["Chart", "Figure", "Diagram", "Graph", "Exhibit", "Figur"]


def caption_pages(pdf_path: Path) -> tuple[str, dict[int, set[int]]]:
    """Return (chosen caption word, {figure_number: set_of_1based_pages}).

    Picks the caption word with the most distinct numbers — the document's own
    convention (Chart / Diagram / ...). A number maps to every page its caption
    text appears on.
    """
    doc = fitz.open(pdf_path)
    per_word: dict[str, dict[int, set[int]]] = {w: defaultdict(set) for w in FIGURE_WORDS}
    for i in range(doc.page_count):
        text = doc[i].get_text()
        for w in FIGURE_WORDS:
            for m in re.finditer(rf"\b{w}[  ]?(\d{{1,3}})\b", text):
                per_word[w][int(m.group(1))].add(i + 1)
    doc.close()
    word = max(per_word, key=lambda w: len(per_word[w]))
    return word, dict(per_word[word])


def captured(outdir: Path) -> tuple[set[int], int]:
    """(1-based pages with a non-skipped figure, total non-skipped figure count)."""
    jsons = list(outdir.glob("*.figures.json"))
    if not jsons:
        raise FileNotFoundError(f"no *.figures.json in {outdir}")
    figs = json.loads(jsons[0].read_text())
    if not isinstance(figs, list):
        figs = figs.get("figures", figs.get("items", []))
    kept = [f for f in figs if not f.get("skipped", False) and "page" in f]
    return {f["page"] for f in kept}, len(kept)


def score(pdf_path: Path, outdir: Path) -> dict:
    word, caps = caption_pages(pdf_path)
    got, n_figs = captured(outdir)
    total = len(caps)
    covered = sorted(n for n, pages in caps.items() if pages & got)
    missed = sorted((n, sorted(caps[n])) for n in caps if not (caps[n] & got))
    return {
        "doc": pdf_path.name,
        "word": word,
        "total": total,
        "covered": len(covered),
        "missed": missed,
        "captured_figures": n_figs,
        "pct": (len(covered) / total * 100) if total else None,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2 or len(argv) % 2 != 0:
        print(__doc__)
        return 2
    pairs = [(Path(argv[i]), Path(argv[i + 1])) for i in range(0, len(argv), 2)]
    results = [score(p, o) for p, o in pairs]

    print(
        f"\n{'Document':34} {'Word':9} {'Caps':>8} {'Covered':>8} {'Coverage':>9} {'Figs':>5}"
    )
    print("-" * 84)
    agg_t = agg_c = 0
    for r in results:
        if r["total"] < 2:
            print(f"{r['doc']:34} {r['word']:9} {'N/A (no caption ground truth)':>36}")
            continue
        agg_t += r["total"]
        agg_c += r["covered"]
        print(
            f"{r['doc']:34} {r['word']:9} {r['total']:8} {r['covered']:8} "
            f"{r['pct']:8.0f}% {r['captured_figures']:5}"
        )
    if agg_t:
        print("-" * 84)
        print(f"{'AGGREGATE':34} {'':9} {agg_t:8} {agg_c:8} {agg_c / agg_t * 100:8.0f}%")

    print("\nMissed figure numbers (caption present, no captured figure on its page):")
    for r in results:
        if r["total"] < 2 or not r["missed"]:
            continue
        items = ", ".join(f"{r['word']} {n} (p{pages[0]})" for n, pages in r["missed"])
        print(f"  {r['doc']}: {items}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
