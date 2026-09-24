#!/usr/bin/env python3
"""The floor reading: plain text extraction, no figures (PRD, Golv, tak och normerat mått).

What a consumer gets from a text-layer dump — pdfium's text per page, nothing
interpreted. Writes eval/runs/floor/<manifest>/<name>.md for every document
that a question file refers to (or every PDF with --all).

    uv run eval/floor.py [--all]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pypdfium2 as pdfium
import yaml

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "runs" / "floor"


def floor_text(pdf: Path) -> str:
    doc = pdfium.PdfDocument(str(pdf))
    return "\n\n".join(
        f"--- Sida {i + 1} ---\n{doc[i].get_textpage().get_text_range().replace(chr(13), '')}" for i in range(len(doc))
    )


def targets(all_docs: bool) -> list[tuple[str, str]]:
    if all_docs:
        return [(p.parent.name, p.stem) for p in sorted((ROOT / "files").glob("*/*.pdf"))]
    out = set()
    for q in (ROOT / "questions").glob("*.yaml"):
        d = yaml.safe_load(q.read_text(encoding="utf-8"))
        out.add((d["manifest"], d["document"]))
    return sorted(out)


if __name__ == "__main__":
    for manifest, name in targets("--all" in sys.argv):
        dest = OUT / manifest / f"{name}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(floor_text(ROOT / "files" / manifest / f"{name}.pdf"), encoding="utf-8")
        print(f"ok    {manifest}/{name}")
