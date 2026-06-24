"""T-035 diagram-detection RECALL bench.

The eval report quantified diagram *precision* (false positives) but never
*recall* — how many real vector diagrams the clustering misses. The clustering
constants in diagrams.py are, by their own comment, "empirically calibrated
against a central-bank monetary-policy report", so recall on other genres is the
open question.

This harness measures recall against hand-annotated ground truth: for each page,
the number of *vector* diagrams the detector should find. Raster image figures are
deliberately excluded — they are images.py's responsibility, not the vector-diagram
clustering's. Recall = (vector diagrams correctly located) / (vector diagrams that
exist). Misses are listed so the responsible threshold can be found.

Ground truth is committed; the PDFs may not be (guarded with skip), so the bench
runs wherever the corpus is present and is reproducible elsewhere.

Run:  python scripts/recall_bench/bench.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
from figmark.diagrams import find_diagram_regions  # noqa: E402

# ---------------------------------------------------------------------------
# Hand-annotated ground truth. `vector_diagrams` maps a 1-indexed page to the
# number of *vector* diagrams on it (the detector's target). Pages absent from
# the map have zero. Raster figures are NOT counted here.
# ---------------------------------------------------------------------------
GROUND_TRUTH = {
    "examples/paper.pdf": {
        "genre": "scientific paper (LaTeX) — Ronneberger et al., U-Net",
        "pages": 8,
        # Only Fig. 1 (p2, the U-net architecture) is a vector diagram. Fig. 2/3/4
        # (p3/p5/p7) are raster microscopy panels → images.py, excluded here.
        "vector_diagrams": {2: 1},
    },
    # --- genre 2+ goes here once a vector-chart-rich non-central-bank PDF is
    # sourced (see T-035). The harness already handles any number of docs. ---
}


def bench_doc(path: Path, truth: dict) -> dict:
    doc = fitz.open(path)
    true_total = hit_total = false_pos = 0
    misses: list[int] = []
    for pno in range(1, len(doc) + 1):
        true_n = truth["vector_diagrams"].get(pno, 0)
        detected = len(find_diagram_regions(doc[pno - 1], pno))
        true_total += true_n
        hit_total += min(detected, true_n)
        false_pos += max(0, detected - true_n)
        if detected < true_n:
            misses.append(pno)
    doc.close()
    recall = hit_total / true_total if true_total else None
    return {
        "true": true_total,
        "hits": hit_total,
        "fp": false_pos,
        "recall": recall,
        "misses": misses,
    }


def main() -> None:
    print("T-035 diagram-detection recall (vector diagrams only)\n")
    grand_true = grand_hits = 0
    measured = 0
    for rel, truth in GROUND_TRUTH.items():
        path = ROOT / rel
        if not path.exists():
            print(f"  SKIP {rel} (not present)")
            continue
        measured += 1
        r = bench_doc(path, truth)
        grand_true += r["true"]
        grand_hits += r["hits"]
        rec = f"{r['recall']:.0%}" if r["recall"] is not None else "n/a"
        print(f"  {truth['genre']}")
        print(
            f"    {rel}: recall {rec}  ({r['hits']}/{r['true']} found)  "
            f"false-positives {r['fp']}  misses on pages {r['misses'] or '—'}"
        )
    if grand_true:
        print(
            f"\n  overall recall: {grand_hits / grand_true:.0%} "
            f"({grand_hits}/{grand_true}) across {measured} document(s)"
        )
    print(
        "\n  NOTE: coverage is currently 1 genre / 1 vector diagram — enough to show\n"
        "  the detector generalises to a non-central-bank vector diagram, but far too\n"
        "  thin to characterise recall. Add vector-chart-rich non-bank documents\n"
        "  (genre 2+) to GROUND_TRUTH to make the number meaningful (T-035)."
    )


if __name__ == "__main__":
    main()
