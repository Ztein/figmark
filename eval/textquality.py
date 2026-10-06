#!/usr/bin/env python3
"""Text quality against native truth (PRD, Framgångsmått → Textkvalitet).

For the test set's Office files the source's own paragraphs (eval/truth/office,
from native_truth.py) are the key. Compares a reading of the native files and a
reading of the same files rendered to PDF, by normalised edit distance
(0 = identical, 1 = nothing in common) after stripping Markdown syntax.

    uv run eval/textquality.py docling-plain
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parent


def norm(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"^\s*\|?\s*:?-{3,}.*$", " ", text, flags=re.M)  # table rule rows
    text = re.sub(r"[#*_|`>]", " ", text)
    text = re.sub(r"^\s*[-+]\s+", " ", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def main(reading: str) -> None:
    rows = []
    for truth in sorted((ROOT / "truth" / "office").glob("*.json")):
        t = json.loads(truth.read_text(encoding="utf-8"))
        if not t["paragraphs"]:
            continue
        key = norm(" ".join(t["paragraphs"]))
        row = {"name": t["name"], "format": t["format"], "chars": len(key)}
        for path_kind, folder in (("native", "office"), ("pdf", "office-pdf")):
            md = ROOT / "runs" / reading / folder / f"{t['name']}.md"
            if md.exists():
                row[path_kind] = round(Levenshtein.normalized_distance(norm(md.read_text(encoding="utf-8")), key), 3)
        if "native" in row or "pdf" in row:
            rows.append(row)
    print("| Document | Format | Characters | Native path | PDF path |\n| --- | --- | --- | --- | --- |")
    for r in rows:
        print(f"| {r['name']} | {r['format']} | {r['chars']} | {r.get('native', '—')} | {r.get('pdf', '—')} |")
    for k in ("native", "pdf"):
        vals = [(r[k], r["chars"]) for r in rows if k in r]
        if vals:
            w = sum(v * c for v, c in vals) / sum(c for _, c in vals)
            print(f"\n{k}: character-weighted mean distance {w:.3f} over {len(vals)} documents")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docling-plain")
