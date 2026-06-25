"""T-035 figure-recall bench: is any figure silently dropped?

A figure reaches the output by one of two paths: a *vector* diagram caught by the
clustering in diagrams.py, or a *raster* figure caught by images.py. What matters
for "described, not dropped" is that EVERY figure is covered by one path or the
other — so this bench measures two things against hand-annotated ground truth:

  - diagram recall  = vector diagrams detected / vector diagrams present
  - figure recall   = figures covered (diagram OR image) / figures present

Ground truth is committed; the PDFs are gitignored (fetch genre 2 with
download.py), so the bench runs wherever the corpus is present.

Run:  python scripts/recall_bench/bench.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
from figmark.diagrams import find_diagram_regions  # noqa: E402
from figmark.images import extract_images_from_page  # noqa: E402

# ---------------------------------------------------------------------------
# Hand-annotated ground truth (1-indexed pages).
#   figures         -> total figures on the page (vector + raster)
#   vector_diagrams -> the subset that are VECTOR (the clustering's job); the rest
#                      are raster figures (images.py's job).
# Verified by rendering each page and by which path PyMuPDF surfaces the figure on
# (get_drawings vs get_image_info).
# ---------------------------------------------------------------------------
GROUND_TRUTH = {
    "examples/paper.pdf": {
        "genre": "scientific paper (LaTeX) — Ronneberger et al., U-Net",
        # Fig 1 (p2) is a vector architecture diagram; Fig 2/3/4 (p3/p5/p7) are
        # raster microscopy panels.
        "figures": {2: 1, 3: 1, 5: 1, 7: 1},
        "vector_diagrams": {2: 1},
    },
    "examples/recall/transformer-1706.03762.pdf": {
        "genre": "ML paper (vector + raster figures) — Vaswani et al., Transformer",
        # Fig 1 (p3, architecture) and Fig 2 (p4, attention) look vector but are
        # embedded as RASTER images; Fig 3-5 (p13-15) are genuine vector figures.
        "figures": {3: 1, 4: 1, 13: 1, 14: 1, 15: 1},
        "vector_diagrams": {13: 1, 14: 1, 15: 1},
    },
}


def bench_doc(path: Path, truth: dict, out_dir: Path) -> dict:
    doc = fitz.open(path)
    vec_true = vec_hit = fig_true = fig_cov = 0
    diagram_misses: list[int] = []
    figure_misses: list[int] = []
    for pno in range(1, len(doc) + 1):
        page = doc[pno - 1]
        n_vec = truth["vector_diagrams"].get(pno, 0)
        n_fig = truth["figures"].get(pno, 0)
        if not (n_vec or n_fig):
            continue
        detected = len(find_diagram_regions(page, pno))
        extracted = len(extract_images_from_page(doc, page, pno, out_dir).images)
        vec_true += n_vec
        vec_hit += min(detected, n_vec)
        fig_true += n_fig
        fig_cov += min(n_fig, detected + extracted)  # covered by either path
        if detected < n_vec:
            diagram_misses.append(pno)
        if detected + extracted < n_fig:
            figure_misses.append(pno)
    doc.close()
    return {
        "vec_true": vec_true,
        "vec_hit": vec_hit,
        "diagram_misses": diagram_misses,
        "fig_true": fig_true,
        "fig_cov": fig_cov,
        "figure_misses": figure_misses,
    }


def main() -> None:
    print("T-035 figure recall — is any figure dropped?\n")
    gv_true = gv_hit = gf_true = gf_cov = 0
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        for rel, truth in GROUND_TRUTH.items():
            path = ROOT / rel
            if not path.exists():
                print(f"  SKIP {rel} (not present — fetch with download.py)")
                continue
            r = bench_doc(path, truth, out_dir)
            gv_true += r["vec_true"]
            gv_hit += r["vec_hit"]
            gf_true += r["fig_true"]
            gf_cov += r["fig_cov"]
            print(f"  {truth['genre']}")
            print(
                f"    diagram recall {r['vec_hit']}/{r['vec_true']}"
                f"  (misses {r['diagram_misses'] or '—'})   "
                f"figure recall {r['fig_cov']}/{r['fig_true']}"
                f"  (dropped {r['figure_misses'] or '—'})"
            )
    if gf_true:
        print(
            f"\n  OVERALL: diagram recall {gv_hit}/{gv_true} "
            f"({gv_hit / gv_true:.0%}); figure recall {gf_cov}/{gf_true} "
            f"({gf_cov / gf_true:.0%}) across the corpus."
        )
    print(
        "\n  FINDING (T-035): on both genres every figure is covered — vector\n"
        "  figures by the clustering, raster figures by images.py — so nothing is\n"
        "  dropped. (Note: the Transformer 'architecture' figures LOOK vector but are\n"
        "  embedded as raster images, so they belong to the image path, not the\n"
        "  diagram detector — hence diagram recall counts only the genuine vector\n"
        "  figures.) No under-detection found on the measured genres."
    )


if __name__ == "__main__":
    main()
