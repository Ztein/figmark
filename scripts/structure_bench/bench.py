"""T-042 heading-detection bench.

Runs the typography heading inference over a document and scores detected headings
against hand-annotated ground truth (precision/recall). Good-enough is the bar, not
100 %. PDFs are gitignored; the bench skips when absent.

Run:  python scripts/structure_bench/bench.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import fitz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
from figmark.pdf_loader import TextBlock, iter_page_blocks  # noqa: E402
from figmark.structure import body_font_size, heading_level, heading_levels  # noqa: E402


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


# Hand-annotated true headings (normalised). Section/subsection/title text.
GROUND_TRUTH = {
    "examples/paper.pdf": {
        _norm("U-Net: Convolutional Networks for Biomedical Image Segmentation"),
        _norm("1 Introduction"),
        _norm("2 Network Architecture"),
        _norm("3 Training"),
        _norm("3.1 Data Augmentation"),
        _norm("4 Experiments"),
        _norm("5 Conclusion"),
        _norm("Acknowlegements"),
        _norm("References"),
    },
}


def detect(path: Path):
    doc = fitz.open(path)
    pages = [
        SimpleNamespace(page_num=i + 1, blocks=iter_page_blocks(doc[i])) for i in range(len(doc))
    ]
    doc.close()
    body = body_font_size(pages)
    size_level, bold_body_level = heading_levels(pages, body)
    found = []
    for page in pages:
        for b in page.blocks:
            if not isinstance(b, TextBlock):
                continue
            lvl = heading_level(b, body, size_level, bold_body_level)
            if lvl:
                found.append((lvl, " ".join(b.text.split())))
    return body, found


def main() -> None:
    for rel, truth in GROUND_TRUTH.items():
        path = ROOT / rel
        if not path.exists():
            print(f"SKIP {rel} (not present)")
            continue
        body, found = detect(path)
        found_norm = {_norm(t) for _, t in found}
        tp = found_norm & truth
        fp = found_norm - truth
        fn = truth - found_norm
        precision = len(tp) / len(found_norm) if found_norm else 0.0
        recall = len(tp) / len(truth) if truth else 0.0
        print(f"{rel}  (body size {body})")
        print("  detected headings (level, text):")
        for lvl, t in found:
            print(f"    H{lvl}  {t}")
        print(
            f"\n  precision {precision:.0%} ({len(tp)}/{len(found_norm)})   "
            f"recall {recall:.0%} ({len(tp)}/{len(truth)})"
        )
        if fp:
            print(f"  false positives: {sorted(fp)}")
        if fn:
            print(f"  missed: {sorted(fn)}")


if __name__ == "__main__":
    main()
