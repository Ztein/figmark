"""figmark convert FILE... [-o DIR]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .cache import DEFAULT_PATH, DescriptionCache
from .convert import convert, converter


def main() -> None:
    ap = argparse.ArgumentParser(prog="figmark")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert documents to Markdown")
    c.add_argument("files", nargs="+", type=Path)
    c.add_argument("-o", "--out", type=Path, default=Path("."), help="output directory")
    c.add_argument("-c", "--config", type=Path, default=None)
    k = sub.add_parser("cache", help="show or clear the figure-description cache")
    k.add_argument("action", choices=["stats", "clear"])
    k.add_argument("-c", "--config", type=Path, default=None)
    args = ap.parse_args()

    if args.cmd == "cache":
        fig = config.load(args.config).figures
        path = DEFAULT_PATH if fig is None or fig.cache is True else Path(str(fig.cache)).expanduser()
        if args.action == "clear":
            path.unlink(missing_ok=True)
            print(f"cleared {path}")
        else:
            n = DescriptionCache(path).size() if path.exists() else 0
            print(f"{path}: {n} descriptions")
        return

    cfg = config.load(args.config)
    if cfg.figures is None:
        print("figmark: no `figures` model configured — figures are left as placeholders", file=sys.stderr)
    conv = converter(cfg)
    args.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for f in args.files:
        try:
            r = convert(f, conv)
        except Exception as e:  # noqa: BLE001 — report every file, then fail loudly at the end
            failed += 1
            print(f"FAIL  {f}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        (args.out / f"{f.stem}.md").write_text(r.markdown, encoding="utf-8")
        missing = f", {r.figures - r.described} NOT described" if cfg.figures and r.described < r.figures else ""
        cached = f", {r.cache_hits} from cache" if r.cache_hits or r.cache_misses else ""
        print(f"ok    {f.name}: {r.pages} pages, {r.figures} figures, {r.described} described{cached}{missing}, {r.seconds}s")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
