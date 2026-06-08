#!/usr/bin/env python3
"""Download sample documents used by the examples and the test suite.

Fetches an openly available paper into examples/paper.pdf so the offline test
suite has a real document to run against (the paper-based tests are written to be
document-agnostic). The larger, document-specific fixtures (report.pdf, guide.pdf)
are optional and described in examples/README.md.

Usage:
    python examples/download_samples.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

# A small open-access paper with embedded raster figures and body text.
# Used as examples/paper.pdf for the document-agnostic paper tests.
SAMPLES = {
    "paper.pdf": "https://arxiv.org/pdf/1505.04597",  # U-Net (Ronneberger et al., 2015)
}


def download(url: str, dest: Path) -> None:
    print(f"  {dest.name} ← {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "figmark-samples/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        data = resp.read()
    dest.write_bytes(data)
    print(f"    saved {len(data) // 1024} KB")


def main() -> int:
    print("Downloading figmark sample documents into examples/ …")
    for name, url in SAMPLES.items():
        dest = HERE / name
        if dest.exists():
            print(f"  {name} already present — skipping")
            continue
        try:
            download(url, dest)
        except Exception as e:  # noqa: BLE001
            print(f"    failed: {e}", file=sys.stderr)
            return 1
    print("Done. See examples/README.md for the optional report.pdf / guide.pdf.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
