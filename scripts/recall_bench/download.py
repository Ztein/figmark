#!/usr/bin/env python3
"""Fetch the non-central-bank recall corpus (T-035).

Downloads each document under examples/recall/ (gitignored), validated by
%PDF magic bytes + PyMuPDF parse. Re-runs skip already-valid files. The PDFs are
third-party and only used locally for benchmarking — never committed or
redistributed.

Usage:
    python scripts/recall_bench/download.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import fitz

OUT = Path(__file__).resolve().parent.parent.parent / "examples" / "recall"
USER_AGENT = "Mozilla/5.0 (compatible; figmark-recall/0.1)"

# name -> (url, license note). arXiv grants a non-exclusive licence to distribute;
# we only render locally for the recall bench.
CORPUS = {
    "transformer-1706.03762.pdf": (
        "https://arxiv.org/pdf/1706.03762",
        "arXiv:1706.03762 (Vaswani et al., 'Attention Is All You Need')",
    ),
}


def valid_pdf(path: Path) -> int:
    try:
        if not path.read_bytes()[:5].startswith(b"%PDF"):
            return 0
        with fitz.open(path) as doc:
            return len(doc)
    except Exception:  # noqa: BLE001
        return 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name, (url, note) in CORPUS.items():
        dest = OUT / name
        if valid_pdf(dest):
            print(f"  ok (cached) {name}")
            continue
        print(f"  fetching {name}  <- {url}  [{note}]")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
                dest.write_bytes(r.read())
        except Exception as e:  # noqa: BLE001
            print(f"    FAILED: {e}")
            failed += 1
            continue
        pages = valid_pdf(dest)
        if not pages:
            print("    FAILED: downloaded file is not a valid PDF")
            dest.unlink(missing_ok=True)
            failed += 1
        else:
            print(f"    saved ({pages} pages)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
