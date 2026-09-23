#!/usr/bin/env python3
"""Download every evaluation document listed in eval/manifests/*.yaml into eval/files/.

    python eval/fetch.py                 # all manifests
    python eval/fetch.py riksbank-ppr    # one manifest

Files land in eval/files/<manifest>/<name>.<format>. Already-downloaded files are
skipped. Documents are public; they are downloaded, never committed.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; figmark-eval)"


def fetch(manifest: Path) -> int:
    docs = yaml.safe_load(manifest.read_text(encoding="utf-8"))["documents"]
    out = ROOT / "files" / manifest.stem
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for d in docs:
        dest = out / f"{d['name']}.{d.get('format', 'pdf')}"
        if dest.exists() and dest.stat().st_size > 0:
            continue
        try:
            req = urllib.request.Request(d["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
                dest.write_bytes(r.read())
            print(f"ok    {manifest.stem}/{dest.name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {manifest.stem}/{d['name']}: {e}", file=sys.stderr)
    return failed


def main() -> int:
    wanted = set(sys.argv[1:])
    manifests = sorted((ROOT / "manifests").glob("*.yaml"))
    failed = sum(fetch(m) for m in manifests if not wanted or m.stem in wanted)
    if failed:
        print(f"{failed} download(s) failed", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
