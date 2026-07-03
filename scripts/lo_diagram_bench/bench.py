"""T-055 LibreOffice diagram bench: charts positive, ruled/zebra tables negative.

LibreOffice-produced PDFs (the whole Office path, T-054) draw chart axes and
gridlines as axis-aligned zero-thickness strokes, which the per-drawing filter
tuned on matplotlib-style PDFs rejects — so LO charts were silently dropped
(T-055). At the same time, LO slide tables (zebra row fills) form drawing
clusters that the detector *wrongly* took for diagrams, double-representing
tables and eating the table extraction (the T-031 overlap gate lets the
diagram win).

This bench pins both failure modes with hand-labelled ground truth:

  - chart recall     = LO vector charts detected / present
  - false positives  = diagram regions reported on labelled table/no-chart pages

Ground truth is committed; the Office source files are the (gitignored)
office-eval corpus at testfiler/office-eval/, converted to PDF on first run via
LibreOffice headless into a cache dir next to the corpus. Files not present are
skipped loudly.

Run:  python scripts/lo_diagram_bench/bench.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
from figmark.diagrams import find_diagram_regions  # noqa: E402

CORPUS = ROOT / "testfiler" / "office-eval"
PDF_CACHE = CORPUS / "lo-pdf-cache"

# ---------------------------------------------------------------------------
# Hand-annotated ground truth (1-indexed pages), labelled by rendering each
# page (2026-07-03). `charts` maps page -> number of vector charts on it;
# `no_chart_pages` are labelled negatives (tables or decoration) where any
# detected region is a false positive.
#
# `known_miss` marks chart pages the clustering detector cannot reach by
# design: LibreOffice draws some chart types as a handful of path objects
# (a radar chart is ~4 drawings), below any sane cluster-size gate. They are
# counted separately so the headline recall reflects the detector's actual
# job, while the misses stay visible instead of quietly dropped from truth.
# ---------------------------------------------------------------------------
GROUND_TRUTH = {
    "poi-bar-chart.pptx": {
        "charts": {1: 1},  # the T-055 repro: plain bar chart
        "no_chart_pages": [],
        "known_miss": {},
    },
    "poi-chart-docx.docx": {
        # p1: bar + line chart. p2: radar + box-and-whisker (8 drawings on the
        # whole page). p3: stock chart drawn as gridlines only (a line-only
        # cluster is indistinguishable from a ruled grid — accepted miss) +
        # sunburst (~13 wedges, below the 30-drawing page gate).
        "charts": {1: 2},
        "no_chart_pages": [],
        "known_miss": {2: 2, 3: 2},
    },
    "poi-three-charts.xlsx": {
        "charts": {2: 2, 3: 1},  # line+pie, area — already detected pre-fix
        "no_chart_pages": [],
        "known_miss": {},
    },
    "cdc-vaccine-effectiveness.pptx": {
        "charts": {1: 1},  # bar chart slide
        "no_chart_pages": [2],  # zebra-striped ruled table
        "known_miss": {},
    },
    "nist-vital.pptx": {
        "charts": {},
        "no_chart_pages": [2, 10, 13, 16, 19, 22, 24],  # small slide tables
        "known_miss": {},
    },
    "skr-patientsakerhet.pptx": {
        "charts": {},
        "no_chart_pages": [3, 4],  # ruled/zebra indicator tables
        "known_miss": {},
    },
    "scb-amneslarare.xlsx": {
        "charts": {},
        "no_chart_pages": [3, 4, 5, 6, 7, 8, 9, 10],  # ruled statistics tables
        "known_miss": {},
    },
    "ons-accessible-tables.xlsx": {
        "charts": {},
        "no_chart_pages": [14, 15, 16, 17],  # borderless tables
        "known_miss": {},
    },
}


def ensure_pdf(office_file: Path) -> Path | None:
    """Convert an office file to PDF via LibreOffice headless, cached on disk."""
    pdf = PDF_CACHE / (office_file.stem + ".pdf")
    if pdf.is_file():
        return pdf
    soffice = shutil.which("soffice")
    if soffice is None:
        return None
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(PDF_CACHE),
            str(office_file),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return pdf if pdf.is_file() else None


def main() -> None:
    print("T-055 LO diagram bench — charts positive, tables negative\n")
    chart_true = chart_hit = fp = 0
    miss_pages: list[str] = []
    fp_pages: list[str] = []
    known_miss_total = known_miss_hit = 0

    for name, truth in GROUND_TRUTH.items():
        src = CORPUS / name
        if not src.is_file():
            print(f"  SKIP {name} (corpus file not present)")
            continue
        pdf = ensure_pdf(src)
        if pdf is None:
            print(f"  SKIP {name} (no soffice on PATH and no cached PDF)")
            continue
        doc = fitz.open(pdf)
        for pno, expected in truth["charts"].items():
            detected = len(find_diagram_regions(doc[pno - 1], pno))
            chart_true += expected
            chart_hit += min(detected, expected)
            status = "ok" if detected >= expected else "MISS"
            if detected < expected:
                miss_pages.append(f"{name} p{pno} ({detected}/{expected})")
            print(f"  [{status:4s}] {name:34s} p{pno:>2}: charts {detected}/{expected}")
        for pno in truth["no_chart_pages"]:
            detected = len(find_diagram_regions(doc[pno - 1], pno))
            fp += detected
            status = "ok" if detected == 0 else "FP"
            if detected:
                fp_pages.append(f"{name} p{pno} ({detected})")
            print(f"  [{status:4s}] {name:34s} p{pno:>2}: negatives {detected} region(s)")
        for pno, expected in truth["known_miss"].items():
            detected = len(find_diagram_regions(doc[pno - 1], pno))
            known_miss_total += expected
            known_miss_hit += min(detected, expected)
        doc.close()

    if chart_true:
        print(
            f"\n  RESULT: chart recall {chart_hit}/{chart_true} "
            f"({chart_hit / chart_true:.0%}), false positives on negative pages: {fp}"
        )
    if miss_pages:
        print(f"  misses: {', '.join(miss_pages)}")
    if fp_pages:
        print(f"  false positives: {', '.join(fp_pages)}")
    print(
        f"  known-miss chart pages (few-drawing LO chart types, outside the "
        f"detector's design): {known_miss_hit}/{known_miss_total} detected"
    )


if __name__ == "__main__":
    main()
