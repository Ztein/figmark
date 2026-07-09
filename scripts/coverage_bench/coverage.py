#!/usr/bin/env python3
"""Figure-coverage metric: did figmark capture the figures a document contains?

Two ground-truth modes, chosen automatically:

* **caption** (captioned PDFs) — ground truth is the document's own numbered
  captions ("Chart N" / "Figure N" / "Diagram N" / …). A figure number is
  *covered* if figmark produced a non-skipped figure on a page where that
  caption appears. Page-level, so a deliberate LOWER BOUND on misses (a page
  with two charts where one is caught counts both covered; a cross-reference can
  over-credit) — it never cries wolf.

* **image** (documents without captions, e.g. a Word file) — ground truth is the
  count of embedded images in the source (icon-sized filtered out). *Covered* =
  distinct images figmark actually extracted, deduplicated by content hash so the
  LibreOffice "same header on every page" phantom repeats collapse to one.

Coverage only — *did we get the figure at all*. It says nothing about description
quality/relevance (that needs an LLM judge). Extraction-independent, so the same
yardstick compares the current detector against any future extraction approach.

Usage:
    python scripts/coverage_bench/coverage.py DOC OUTPUT_DIR [DOC2 OUTDIR2 ...]

Each OUTPUT_DIR is the figmark run dir containing <name>.figures.json.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import fitz

# Caption words that denote an interpretable figure. "Table" is excluded on
# purpose — tables go through a different pipeline path, not the figure path.
FIGURE_WORDS = ["Chart", "Figure", "Diagram", "Graph", "Exhibit", "Figur"]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".emf", ".wmf", ".gif", ".tif", ".tiff", ".bmp"}
OFFICE_SUFFIXES = {".docx", ".pptx", ".xlsx"}
# Bytes floor to drop icons/bullets — a rough proxy for "bigger than ~50x50".
_MIN_MEDIA_BYTES = 2000


def caption_pages(pdf_path: Path) -> tuple[str, dict[int, set[int]]]:
    """Return (chosen caption word, {figure_number: set_of_1based_pages})."""
    doc = fitz.open(pdf_path)
    per_word: dict[str, dict[int, set[int]]] = {w: defaultdict(set) for w in FIGURE_WORDS}
    for i in range(doc.page_count):
        text = doc[i].get_text()
        for w in FIGURE_WORDS:
            # \s matches nbsp/thin-space too (str patterns) — the exact
            # separator varies by publisher, and the metric must be stable.
            for m in re.finditer(rf"\b{w}\s{{0,3}}(\d{{1,3}})\b", text):
                per_word[w][int(m.group(1))].add(i + 1)
    doc.close()
    word = max(per_word, key=lambda w: len(per_word[w]))
    return word, dict(per_word[word])


def captured(outdir: Path) -> tuple[set[int], int]:
    """(1-based pages with a non-skipped figure, total non-skipped figure count)."""
    figs = _load_figures(outdir)
    kept = [f for f in figs if not f.get("skipped", False) and "page" in f]
    return {f["page"] for f in kept}, len(kept)


def _load_figures(outdir: Path) -> list[dict]:
    jsons = list(outdir.glob("*.figures.json"))
    if not jsons:
        raise FileNotFoundError(f"no *.figures.json in {outdir}")
    figs = json.loads(jsons[0].read_text())
    return figs if isinstance(figs, list) else figs.get("figures", figs.get("items", []))


def source_image_count(path: Path) -> int:
    """Unique embedded images in the source, icons filtered out."""
    if path.suffix.lower() in OFFICE_SUFFIXES:
        with zipfile.ZipFile(path) as z:
            return sum(
                1
                for info in z.infolist()
                if re.search(r"/media/[^/]+$", info.filename)
                and Path(info.filename).suffix.lower() in IMAGE_EXTS
                and info.file_size >= _MIN_MEDIA_BYTES
            )
    doc = fitz.open(path)
    xrefs: set[int] = set()
    for i in range(doc.page_count):
        for img in doc[i].get_images(full=True):
            xref, _, w, h = img[0], img[1], img[2], img[3]
            if w > 50 and h > 50:
                xrefs.add(xref)
    doc.close()
    return len(xrefs)


def captured_unique_images(outdir: Path) -> int:
    """Distinct extracted images by content hash (collapses LO phantom repeats)."""
    seen: set[str] = set()
    for sub in ("images", "diagrams"):
        d = outdir / sub
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file():
                    seen.add(hashlib.md5(f.read_bytes()).hexdigest())
    return len(seen)


def score(source_path: Path, outdir: Path) -> dict:
    word, caps = ("-", {})
    if source_path.suffix.lower() == ".pdf":
        word, caps = caption_pages(source_path)

    if len(caps) >= 2:  # caption mode
        got, n_figs = captured(outdir)
        covered = sorted(n for n, pages in caps.items() if pages & got)
        missed = sorted((n, sorted(caps[n])) for n in caps if not (caps[n] & got))
        total = len(caps)
        return {
            "doc": source_path.name,
            "mode": "caption",
            "word": word,
            "total": total,
            "covered": len(covered),
            "captured": n_figs,
            "missed": missed,
            "pct": len(covered) / total * 100 if total else None,
        }

    # image mode (no captions — e.g. a Word file)
    total = source_image_count(source_path)
    uniq = captured_unique_images(outdir)
    covered = min(uniq, total)
    return {
        "doc": source_path.name,
        "mode": "image",
        "word": "img",
        "total": total,
        "covered": covered,
        "captured": uniq,
        "missed": [],
        "pct": covered / total * 100 if total else None,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2 or len(argv) % 2 != 0:
        print(__doc__)
        return 2
    pairs = [(Path(argv[i]), Path(argv[i + 1])) for i in range(0, len(argv), 2)]
    results = [score(p, o) for p, o in pairs]

    print(f"\n{'Document':34} {'Mode':8} {'GT':>5} {'Covered':>8} {'Coverage':>9} {'Captured':>9}")
    print("-" * 80)
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in results:
        cov = "N/A" if r["pct"] is None else f"{r['pct']:.0f}%"
        d, m, t, c, cap = r["doc"], r["mode"], r["total"], r["covered"], r["captured"]
        print(f"{d:34} {m:8} {t:5} {c:8} {cov:>9} {cap:8}")
        if r["pct"] is not None:
            agg[r["mode"]][0] += r["total"]
            agg[r["mode"]][1] += r["covered"]
    print("-" * 80)
    for mode, (t, c) in agg.items():
        print(f"{'AGGREGATE (' + mode + ')':34} {'':8} {t:5} {c:8} {c / t * 100:8.0f}%")

    print("\nMissed figures (caption present, no captured figure on its page):")
    any_missed = False
    for r in results:
        if r["missed"]:
            any_missed = True
            items = ", ".join(f"{r['word']} {n} (p{pages[0]})" for n, pages in r["missed"])
            print(f"  {r['doc']}: {items}")
    if not any_missed:
        print("  (none in caption-mode docs)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
