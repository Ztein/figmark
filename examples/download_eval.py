#!/usr/bin/env python3
"""Download and validate the evaluation corpus (examples/eval/manifest.yaml).

Each document is fetched into examples/eval/<name>.pdf (gitignored), then
validated: %PDF magic bytes and parseable by PyMuPDF (page count > 0). Already
present, valid files are skipped, so re-runs are cheap.

Usage:
    python examples/download_eval.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import fitz
import yaml

HERE = Path(__file__).resolve().parent / "eval"
USER_AGENT = "Mozilla/5.0 (compatible; figmark-eval/0.1)"


def valid_pdf(path: Path) -> int:
    """Return the page count if path is a readable PDF, else 0."""
    try:
        if not path.read_bytes()[:5].startswith(b"%PDF"):
            return 0
        doc = fitz.open(path)
        n = doc.page_count
        doc.close()
        return n
    except Exception:  # noqa: BLE001
        return 0


def fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp:
        dest.write_bytes(resp.read())


def main() -> int:
    manifest = yaml.safe_load((HERE / "manifest.yaml").read_text(encoding="utf-8"))
    docs = manifest["documents"]
    print(f"Evaluation corpus: {len(docs)} documents → {HERE}/")
    ok, failed = 0, []
    for doc in docs:
        name, url = doc["name"], doc["url"]
        dest = HERE / f"{name}.pdf"
        if dest.exists() and valid_pdf(dest):
            print(f"  {name}: already present ({valid_pdf(dest)} pages)")
            ok += 1
            continue
        try:
            fetch(url, dest)
        except Exception as e:  # noqa: BLE001
            print(f"  {name}: DOWNLOAD FAILED ({type(e).__name__})", file=sys.stderr)
            failed.append(name)
            continue
        pages = valid_pdf(dest)
        if pages:
            print(f"  {name}: {dest.stat().st_size // 1024} KB, {pages} pages")
            ok += 1
        else:
            print(f"  {name}: INVALID PDF", file=sys.stderr)
            dest.unlink(missing_ok=True)
            failed.append(name)
    print(f"\n{ok} valid, {len(failed)} failed{': ' + ', '.join(failed) if failed else ''}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
