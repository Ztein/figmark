#!/usr/bin/env python3
"""How often does the same figure image come back? (Phase 2: should figures be cached?)

For every figure Docling found in the PDFs (eval/inventory/), render its box at a
fixed resolution and hash it two ways:
  exact     — SHA-1 of the pixels. A hit is safe to reuse a description for.
  near      — 16×16 grey thumbnail, quantised (an average hash). Catches the same
              logo drawn at a slightly different position, but also two charts in
              the same template — an upper bound, not something to reuse blindly.
Counts a figure as a repeat when an earlier figure (same document, or any
earlier document) has the same hash, split by figure class and by Docling's 5 %
size cut-off.

    uv run eval/duplicates.py
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent
DPI = 100
CUTOFF = 0.05  # Docling's picture_area_threshold


def hashes(img) -> tuple[str, str]:
    exact = hashlib.sha1(img.tobytes()).hexdigest()
    small = img.convert("L").resize((16, 16))
    px = list(small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata())
    mean = sum(px) / len(px)
    near = "".join("1" if p > mean else "0" for p in px)
    return exact, near


def main() -> None:
    seen_doc: dict[str, set] = defaultdict(set)
    seen_any: dict[str, set] = {"exact": set(), "near": set()}
    stats = Counter()
    by_class: dict[str, Counter] = defaultdict(Counter)
    for inv in sorted((ROOT / "inventory").glob("*/*.json")):
        r = json.loads(inv.read_text(encoding="utf-8"))
        if r.get("format") != "pdf" or not r.get("figures"):
            continue
        pdf = pdfium.PdfDocument(str(ROOT / "files" / r["manifest"] / f"{r['name']}.pdf"))
        pages: dict[int, object] = {}
        doc_seen = {"exact": set(), "near": set()}
        for f in r["figures"]:
            if not f["bbox"]:
                continue
            page = pdf[f["page"] - 1]
            if f["page"] not in pages:
                pages[f["page"]] = page.render(scale=DPI / 72).to_pil().convert("RGB")
            x0, y0, x1, y1 = f["bbox"]
            area = (x1 - x0) * (y1 - y0) / (page.get_width() * page.get_height())
            crop = pages[f["page"]].crop(tuple(round(v * DPI / 72) for v in (x0, y0, x1, y1)))
            if crop.width < 2 or crop.height < 2:
                continue
            ex, nr = hashes(crop)
            size = "large" if area >= CUTOFF else "small"
            cls = f["class"] or "none"
            stats[f"figures_{size}"] += 1
            by_class[cls]["figures"] += 1
            for kind, h in (("exact", ex), ("near", nr)):
                if h in doc_seen[kind]:
                    stats[f"{kind}_in_doc_{size}"] += 1
                    by_class[cls][f"{kind}_in_doc"] += 1
                elif h in seen_any[kind]:
                    stats[f"{kind}_across_{size}"] += 1
                    by_class[cls][f"{kind}_across"] += 1
                doc_seen[kind].add(h)
                seen_any[kind].add(h)
        pages.clear()
    out = {"stats": dict(stats), "by_class": {k: dict(v) for k, v in by_class.items()}}
    (ROOT / "runs").mkdir(exist_ok=True)
    (ROOT / "runs" / "duplicates.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for size in ("large", "small"):
        n = stats[f"figures_{size}"]
        print(f"\n{size} figures (≥/< 5 % of the page): {n}")
        for kind in ("exact", "near"):
            d, a = stats[f"{kind}_in_doc_{size}"], stats[f"{kind}_across_{size}"]
            print(f"  {kind:5}: repeat within document {d} ({d / n:.1%}), first seen in an earlier document {a} ({a / n:.1%})")
    print("\n| Class | Figures | Exact in doc | Exact across | Near in doc | Near across |\n| --- | --- | --- | --- | --- | --- |")
    for cls, c in sorted(by_class.items(), key=lambda kv: -kv[1]["figures"]):
        print(f"| {cls} | {c['figures']} | {c['exact_in_doc']} | {c['exact_across']} | {c['near_in_doc']} | {c['near_across']} |")


if __name__ == "__main__":
    main()
