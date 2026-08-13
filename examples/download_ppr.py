#!/usr/bin/env python3
"""Download the Riksbank Monetary Policy Report (PPR) corpus.

The Riksbank publishes its Monetary Policy Reports (penningpolitisk rapport)
and Updates (penningpolitisk uppdatering) as tagged PDFs. From around 2021 the
figures carry **hand-written accessibility descriptions** (`/Alt` entries in
the PDF structure tree) — a human-authored description of every chart, made by
the publisher. That is a rare external baseline for figure-description quality
(T-082): can figmark describe a chart at least as well as the publisher's own
accessibility text?

This script keeps the corpus in sync:

1. Scrapes the riksbank.se publication listing (server-side ``?year=`` filter)
   for every report/update PDF.
2. Reconciles with ``examples/eval/ppr/manifest.yaml`` — new publications are
   added; a manifest URL that disappears from the listing is reported loudly
   (URL rot), never silently dropped.
3. Downloads every manifest entry into ``examples/eval/ppr/files/`` (PDFs are
   gitignored — only the manifest and this script are committed).
4. Validates each file (%PDF magic + parseable by PyMuPDF) and counts the
   figure alt-texts, so the census of "which years have hand-written
   descriptions" is reproducible.

Usage:
    python examples/download_ppr.py              # sync manifest + download all
    python examples/download_ppr.py --no-scrape  # offline: download from manifest only
"""

from __future__ import annotations

import re
import sys
import time
import urllib.request
from pathlib import Path

import fitz
import yaml

BASE = "https://www.riksbank.se"
LISTING = BASE + "/sv/press-och-publicerat/publikationer/penningpolitisk-rapport/"
USER_AGENT = "Mozilla/5.0 (compatible; figmark-eval/0.1)"

HERE = Path(__file__).resolve().parent / "eval" / "ppr"
MANIFEST = HERE / "manifest.yaml"
FILES = HERE / "files"

MONTHS = {
    "januari": "01", "februari": "02", "mars": "03", "april": "04",
    "maj": "05", "juni": "06", "juli": "07", "augusti": "08",
    "september": "09", "oktober": "10", "november": "11", "december": "12",
}
MONTH_NAMES = {v: k for k, v in MONTHS.items()}

# Alt-texts shorter than this are structural boilerplate ("Visuell markering
# för faktaruta"), not figure descriptions. The shortest real chart description
# observed in the corpus probe was ~120 chars; boilerplate maxes out well under
# this. Census only — nothing downstream gates on it.
MIN_DESCRIPTION_CHARS = 60


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def entry_from_url(path: str) -> dict:
    """Derive a manifest entry from a riksbank.se PDF path. Fails loud on an
    unrecognised filename — a new naming scheme must be looked at, not guessed."""
    fname = path.rsplit("/", 1)[-1]
    m = re.match(r"penningpolitisk-(rapport|uppdatering)-+([a-z]+)-(\d{4})\.pdf", fname)
    if m:
        kind, month_name, year = m.groups()
        if month_name not in MONTHS:
            raise SystemExit(f"Unknown Swedish month {month_name!r} in {fname}")
        month = MONTHS[month_name]
    else:
        # Legacy scheme: rap_ppr_YYMMDD_sve_<junk>.pdf (used once, Sep 2017).
        m = re.match(r"rap_ppr_(\d{2})(\d{2})\d{2}_sve.*\.pdf", fname)
        if not m:
            raise SystemExit(
                f"Unrecognised PPR filename {fname!r} — the listing has a new "
                "naming scheme; extend entry_from_url() after inspecting it."
            )
        year, month = "20" + m.group(1), m.group(2)
        kind = "rapport"
    prefix = "ppr" if kind == "rapport" else "ppu"
    label = "Penningpolitisk rapport" if kind == "rapport" else "Penningpolitisk uppdatering"
    return {
        "name": f"{prefix}-{year}-{month}",
        "url": BASE + path,
        "source": f"Riksbanken, {label} {MONTH_NAMES[month]} {year}",
        "type": kind,
        "language": "sv",
    }


def scrape_listing() -> list[dict]:
    """All report/update PDFs from the year-filtered listing pages."""
    index = fetch(LISTING).decode("utf-8", "replace")
    years = sorted(set(re.findall(r'data-value="(\d{4})"', index)))
    if not years:
        raise SystemExit("No year filters found on the listing page — layout changed?")
    paths: set[str] = set()
    for year in years:
        page = fetch(f"{LISTING}?year={year}").decode("utf-8", "replace")
        found = re.findall(r'href="(/globalassets/[^"]*ppr[^"]*\.pdf)"', page)
        if not found:
            raise SystemExit(f"Listing for {year} contains no PDF links — layout changed?")
        paths.update(found)
        time.sleep(0.3)
    return [entry_from_url(p) for p in sorted(paths)]


def sync_manifest(scraped: list[dict]) -> list[dict]:
    """Merge scraped entries into the manifest; report drift loudly."""
    manifest: list[dict] = []
    if MANIFEST.exists():
        manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["documents"]
    by_name = {e["name"]: e for e in manifest}
    added = []
    for e in scraped:
        if e["name"] not in by_name:
            added.append(e)
            by_name[e["name"]] = e
        elif by_name[e["name"]]["url"] != e["url"]:
            raise SystemExit(
                f"URL changed for {e['name']}: manifest has "
                f"{by_name[e['name']]['url']}, listing has {e['url']}. "
                "Riksbanken moved the file — update the manifest deliberately."
            )
    scraped_names = {e["name"] for e in scraped}
    gone = sorted(set(by_name) - scraped_names)
    if gone:
        print(f"WARNING: {len(gone)} manifest entries no longer in the listing "
              f"(kept, but check for URL rot): {', '.join(gone)}")
    merged = sorted(by_name.values(), key=lambda e: e["name"])
    if added or not MANIFEST.exists():
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# Riksbank PPR corpus — every Monetary Policy Report/Update on riksbank.se.\n"
            "# Maintained by examples/download_ppr.py (scrape + merge); PDFs land in\n"
            "# files/ (gitignored) — only this manifest and the script are committed.\n"
            "# Purpose: the publisher's hand-written figure alt-texts are an external\n"
            "# quality baseline for figure descriptions (T-082).\n"
        )
        MANIFEST.write_text(
            header + yaml.safe_dump({"documents": merged}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        for e in added:
            print(f"  manifest + {e['name']}")
    return merged


def figure_alt_texts(path: Path) -> int:
    """Count hand-written figure descriptions (/Alt strings) in the tag tree."""
    doc = fitz.open(path)
    n = 0
    for xref in range(1, doc.xref_length()):
        try:
            kind, value = doc.xref_get_key(xref, "Alt")
        except Exception:
            continue
        if kind == "string" and len(value) >= MIN_DESCRIPTION_CHARS:
            n += 1
    return n


def valid_pdf(path: Path) -> int:
    try:
        if not path.read_bytes()[:5].startswith(b"%PDF"):
            return 0
        return fitz.open(path).page_count
    except Exception:
        return 0


def main() -> None:
    if "--no-scrape" in sys.argv:
        if not MANIFEST.exists():
            raise SystemExit("--no-scrape needs an existing manifest.")
        docs = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["documents"]
    else:
        docs = sync_manifest(scrape_listing())

    FILES.mkdir(parents=True, exist_ok=True)
    failures = []
    print(f"{'name':<14} {'pages':>5} {'alt-texts':>9}")
    for e in docs:
        dest = FILES / f"{e['name']}.pdf"
        if not (dest.exists() and valid_pdf(dest)):
            try:
                dest.write_bytes(fetch(e["url"]))
            except Exception as exc:  # noqa: BLE001 — collected and reported, run continues
                failures.append(f"{e['name']}: download failed ({exc})")
                continue
        pages = valid_pdf(dest)
        if not pages:
            failures.append(f"{e['name']}: not a valid PDF")
            dest.unlink()
            continue
        print(f"{e['name']:<14} {pages:>5} {figure_alt_texts(dest):>9}")

    if failures:
        print(f"\n{len(failures)} FAILURES:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        raise SystemExit(1)
    print(f"\nOK — {len(docs)} documents in {FILES}")


if __name__ == "__main__":
    main()
