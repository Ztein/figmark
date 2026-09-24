#!/usr/bin/env python3
"""Inventory the evaluation documents (PRD, Utvärdering → Inventera).

A cheap first pass over every downloaded document: format, pages, whether a
text layer exists, and the figures Docling finds with the class its figure
classifier gives them. One JSON per document lands in
eval/inventory/<manifest>/<name>.json; `--summary` writes eval/inventory.csv.

    uv run eval/inventory.py                  # every document not yet inventoried
    uv run eval/inventory.py riksbank-ppr     # one manifest
    uv run eval/inventory.py --summary

Office files are read as zip archives (media, chart parts, SmartArt parts);
Docling only runs on PDFs, without OCR or table structure, since only layout
and figure classes are needed here.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import zipfile
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "inventory"
TEXT_LAYER_MIN_CHARS = 50  # a page with fewer extractable characters counts as image-only


def manifests(only: str | None) -> dict[str, list[dict]]:
    out = {}
    for m in sorted((ROOT / "manifests").glob("*.yaml")):
        if only and m.stem != only:
            continue
        out[m.stem] = yaml.safe_load(m.read_text(encoding="utf-8"))["documents"]
    return out


def pdf_converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(
        do_ocr=False, do_table_structure=False, do_picture_classification=True
    )
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def text_layer(path: Path) -> tuple[int, int]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    with_text = sum(
        len(doc[i].get_textpage().get_text_range().strip()) >= TEXT_LAYER_MIN_CHARS
        for i in range(len(doc))
    )
    return len(doc), with_text


def bbox_top_left(doc, prov) -> list[float]:
    """[x0, y0, x1, y1] in PDF points, origin top-left, y growing downwards."""
    b = prov.bbox.to_top_left_origin(doc.pages[prov.page_no].size.height)
    return [round(v, 1) for v in (b.l, b.t, b.r, b.b)]


def inventory_pdf(path: Path, converter) -> dict:
    pages, with_text = text_layer(path)
    t0 = time.time()
    doc = converter.convert(str(path)).document
    figures = []
    for pic in doc.pictures:
        prov = pic.prov[0] if pic.prov else None
        cls = pic.meta.classification if pic.meta else None
        top = cls.predictions[0] if cls and cls.predictions else None
        figures.append(
            {
                "page": prov.page_no if prov else None,
                "bbox": bbox_top_left(doc, prov) if prov else None,
                "class": top.class_name if top else None,
                "confidence": round(top.confidence, 3) if top and top.confidence else None,
                "caption": pic.caption_text(doc) or None,
            }
        )
    return {
        "pages": pages,
        "pages_with_text": with_text,
        "figures": figures,
        "bbox_origin": "top-left",
        "seconds": round(time.time() - t0, 1),
        "tool": f"docling {version('docling')}",
    }


def inventory_office(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        app = z.read("docProps/app.xml").decode("utf-8", "replace") if "docProps/app.xml" in names else ""
    count = lambda pat: sum(bool(re.search(pat, n)) for n in names)  # noqa: E731
    units = re.search(r"<(Pages|Slides)>(\d+)<", app)
    return {
        "pages": int(units.group(2)) if units else count(r"^(ppt/slides/slide|xl/worksheets/sheet)\d+\.xml$") or None,
        "images": count(r"/media/"),
        "charts": count(r"/charts/chart\d+\.xml$"),
        "smartart": count(r"/diagrams/data\d+\.xml$"),
        "tool": "zip",
    }


def run(only: str | None) -> None:
    converter = None
    for manifest, docs in manifests(only).items():
        for d in docs:
            fmt = d.get("format", "pdf")
            src = ROOT / "files" / manifest / f"{d['name']}.{fmt}"
            dest = OUT / manifest / f"{d['name']}.json"
            if dest.exists() or not src.exists():
                continue
            try:
                if fmt == "pdf":
                    converter = converter or pdf_converter()
                    rec = inventory_pdf(src, converter)
                else:
                    rec = inventory_office(src)
            except Exception as e:  # noqa: BLE001 — record and move on, loudly
                rec = {"error": f"{type(e).__name__}: {e}"}
                print(f"FAIL  {manifest}/{d['name']}: {rec['error']}", file=sys.stderr)
            rec = {"name": d["name"], "manifest": manifest, "format": fmt, "language": d.get("language"), **rec}
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            n = len(rec.get("figures", [])) or rec.get("images", 0)
            print(f"ok    {manifest}/{d['name']}: {rec.get('pages')} pages, {n} figures", flush=True)


def summary() -> None:
    rows = []
    for f in sorted(OUT.rglob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        classes = Counter(x["class"] for x in r.get("figures", []))
        rows.append(
            {
                "manifest": r["manifest"],
                "name": r["name"],
                "format": r["format"],
                "language": r.get("language"),
                "pages": r.get("pages"),
                "pages_with_text": r.get("pages_with_text"),
                "figures": sum(classes.values()) if r["format"] == "pdf" else r.get("images"),
                "charts_xml": r.get("charts"),
                "smartart": r.get("smartart"),
                "classes": " ".join(f"{k}:{v}" for k, v in classes.most_common()),
                "error": r.get("error"),
            }
        )
    with open(ROOT / "inventory.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} documents → eval/inventory.csv")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--summary" in args:
        summary()
    else:
        run(args[0] if args else None)
