#!/usr/bin/env python3
"""Ground truth from native Office files (PRD, Utvärdering → Facit nästan gratis).

For every .docx/.pptx/.xlsx in eval/files/office/:
  - render it to PDF with LibreOffice headless → eval/files/office-pdf/<name>.pdf,
    so it can also go down the PDF path;
  - read the source's own truth → eval/truth/office/<name>.json:
      charts    — type, title, and per series its name, categories and exact values
                  from the chart XML caches;
      smartart  — nodes and parent→child connections from the SmartArt data model;
      paragraphs — the text, paragraph by paragraph (docx and pptx).

Both outputs are derived from the downloaded files and stay out of git.

    uv run eval/native_truth.py
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "files" / "office"
PDF = ROOT / "files" / "office-pdf"
OUT = ROOT / "truth" / "office"

NS = {
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


def text_of(el) -> str:
    return "".join(t.text or "" for t in el.iter(f"{{{NS['a']}}}t")).strip() if el is not None else ""


def cache(el) -> list:
    """Points of a strRef/numRef/strLit/numLit cache, in index order (gaps as None)."""
    if el is None:
        return []
    pts = {}
    count = 0
    for c in el.iter():
        if c.tag == f"{{{NS['c']}}}ptCount":
            count = max(count, int(c.get("val")))
        if c.tag == f"{{{NS['c']}}}pt":
            v = c.find("c:v", NS)
            pts[int(c.get("idx"))] = v.text if v is not None else None
    vals = [pts.get(i) for i in range(max(count, max(pts, default=-1) + 1))]
    try:
        return [float(v) if v is not None else None for v in vals]
    except ValueError:
        return vals


def chart(xml: bytes) -> dict:
    root = ET.fromstring(xml)
    if root.tag.startswith("{http://schemas.microsoft.com/office/drawing/2014/chartex}"):
        kind = re.search(rb'layoutId="(\w+)"', xml)
        return {"type": kind.group(1).decode() if kind else "chartex", "series": [], "note": "chartex: values not read"}
    title = text_of(root.find("c:chart/c:title", NS))
    plot = root.find("c:chart/c:plotArea", NS)
    types, series = [], []
    for grp in plot:
        tag = grp.tag.split("}")[1]
        if not tag.endswith("Chart"):
            continue
        direction = grp.find("c:barDir", NS)
        types.append(tag + (f"/{direction.get('val')}" if direction is not None else ""))
        for ser in grp.findall("c:ser", NS):
            name = cache(ser.find("c:tx", NS))
            series.append(
                {
                    "chart_type": tag,
                    "name": name[0] if name else None,
                    "categories": cache(ser.find("c:cat", NS)) or cache(ser.find("c:xVal", NS)),
                    "values": cache(ser.find("c:val", NS)) or cache(ser.find("c:yVal", NS)),
                }
            )
    axes = [text_of(ax.find("c:title", NS)) for ax in plot if ax.tag.split("}")[1].endswith("Ax")]
    return {"type": "+".join(types), "title": title or None, "axis_titles": [a for a in axes if a], "series": series}


def smartart(xml: bytes) -> dict:
    root = ET.fromstring(xml)
    nodes = {}
    for pt in root.iterfind("dgm:ptLst/dgm:pt", NS):
        if pt.get("type") in (None, "node", "doc"):
            nodes[pt.get("modelId")] = {"type": pt.get("type") or "node", "text": text_of(pt.find("dgm:t", NS))}
    edges = [
        (c.get("srcId"), c.get("destId"))
        for c in root.iterfind("dgm:cxnLst/dgm:cxn", NS)
        if c.get("type") in (None, "parOf") and c.get("srcId") in nodes and c.get("destId") in nodes
    ]
    label = lambda i: nodes[i]["text"] or ("(root)" if nodes[i]["type"] == "doc" else "")  # noqa: E731
    return {
        "nodes": [n["text"] for n in nodes.values() if n["type"] == "node" and n["text"]],
        "edges": [[label(s), label(d)] for s, d in edges],
    }


def paragraphs(z: zipfile.ZipFile, fmt: str) -> list[str]:
    if fmt == "docx":
        root = ET.fromstring(z.read("word/document.xml"))
        paras = ["".join(t.text or "" for t in p.iter(f"{{{NS['w']}}}t")) for p in root.iter(f"{{{NS['w']}}}p")]
    elif fmt == "pptx":
        slides = sorted(
            (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"\d+", n).group()),
        )
        paras = [text_of(p) for s in slides for p in ET.fromstring(z.read(s)).iter(f"{{{NS['a']}}}p")]
    else:
        return []
    return [p.strip() for p in paras if p.strip()]


def to_pdf(src: Path) -> None:
    dest = PDF / f"{src.stem}.pdf"
    if dest.exists():
        return
    PDF.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:  # own profile: no clash with a running LibreOffice
        subprocess.run(
            ["soffice", f"-env:UserInstallation=file://{profile}", "--headless",
             "--convert-to", "pdf", "--outdir", str(PDF), str(src)],
            check=True, capture_output=True, timeout=300,
        )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for src in sorted(SRC.iterdir()):
        fmt = src.suffix.lstrip(".")
        if fmt not in ("docx", "pptx", "xlsx"):
            continue
        to_pdf(src)
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            num = lambda n: int(re.search(r"(\d+)\.xml$", n).group(1))  # noqa: E731
            charts = [
                {"part": n, **chart(z.read(n))}
                for n in sorted((n for n in names if re.search(r"/charts/chart\d+\.xml$", n)), key=num)
            ]
            smart = [
                {"part": n, **smartart(z.read(n))}
                for n in sorted((n for n in names if re.search(r"/diagrams/data\d+\.xml$", n)), key=num)
            ]
            rec = {"name": src.stem, "format": fmt, "charts": charts, "smartart": smart, "paragraphs": paragraphs(z, fmt)}
        (OUT / f"{src.stem}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"ok    {src.name}: {len(charts)} charts, {len(smart)} smartart, {len(rec['paragraphs'])} paragraphs")


if __name__ == "__main__":
    main()
