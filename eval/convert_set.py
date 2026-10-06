#!/usr/bin/env python3
"""Run figmark over a set of documents and store the output as a reading.

    uv run eval/convert_set.py docling                    # documents with questions
    uv run eval/convert_set.py docling --testset          # all of test set v1
    uv run eval/convert_set.py docling-plain --no-figures # Docling without figure descriptions
    uv run eval/convert_set.py docling --office           # test set Office files, read natively
    uv run eval/convert_set.py docling --office-pdf       # the same files rendered to PDF

Writes eval/runs/<reading>/<manifest>/<name>.md and run.json (per document:
pages, figures, described, seconds, or the error). Already converted documents
are skipped, so a run can be resumed. Each document runs in its own process, so
a crash or an out-of-memory kill is recorded as that document's failure instead
of ending the run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))

from figmark import config  # noqa: E402
from figmark.convert import convert, converter  # noqa: E402


def targets(args) -> list[tuple[str, str, Path]]:
    if args.testset or args.office_pdf or args.office:
        docs = yaml.safe_load((ROOT / "testset-v1.yaml").read_text(encoding="utf-8"))["documents"]
        out = []
        for d in docs:
            if args.office_pdf or args.office:
                if d["manifest"] == "office":
                    out.append(("office-pdf", d["name"], ROOT / "files" / "office-pdf" / f"{d['name']}.pdf")
                               if args.office_pdf else ("office", d["name"], ROOT / "files" / "office" / f"{d['name']}.{d['format']}"))
            else:
                out.append((d["manifest"], d["name"], ROOT / "files" / d["manifest"] / f"{d['name']}.{d['format']}"))
        return out
    seen = set()
    for q in sorted((ROOT / "questions").glob("*.yaml")):
        d = yaml.safe_load(q.read_text(encoding="utf-8"))
        seen.add((d["manifest"], d["document"]))
    return [(m, n, ROOT / "files" / m / f"{n}.pdf") for m, n in sorted(seen)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reading")
    ap.add_argument("--testset", action="store_true")
    ap.add_argument("--office-pdf", action="store_true")
    ap.add_argument("--office", action="store_true", help="test set Office files, read natively")
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--config", default=str(ROOT.parent / "figmark.yaml"))
    ap.add_argument("--one", nargs=2, metavar=("SRC", "DEST"), help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.one:
        src, dest = Path(args.one[0]), Path(args.one[1])
        cfg = config.Config() if args.no_figures else config.load(args.config)
        r = convert(src, converter(cfg))
        dest.write_text(r.markdown, encoding="utf-8")
        print(json.dumps({"pages": r.pages, "figures": r.figures, "described": r.described, "seconds": r.seconds}))
        return

    cfg = config.Config() if args.no_figures else config.load(args.config)
    base = ROOT / "runs" / args.reading
    log_path = base / "run.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else {"docs": {}}
    log["pipeline"] = {
        "figmark": "phase-1 candidate: Docling defaults + built-in picture description",
        "docling": version("docling"),
        "figure_model": cfg.figures.model if cfg.figures else None,
        "figure_prompt": (cfg.figures.prompt or "Docling default") if cfg.figures else None,
    }
    for manifest, name, src in targets(args):
        dest = base / manifest / f"{name}.md"
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        key = f"{manifest}/{name}"
        cmd = [sys.executable, __file__, args.reading, "--config", args.config, "--one", str(src), str(dest)]
        if args.no_figures:
            cmd.append("--no-figures")
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            log["docs"][key] = json.loads(p.stdout.strip().splitlines()[-1])
            d = log["docs"][key]
            print(f"ok    {key}: {d['pages']} p, {d['figures']} fig, {d['described']} described, {d['seconds']}s", flush=True)
        else:  # robustness is measured, so record and go on
            err = (p.stderr.strip().splitlines() or [f"killed by signal {-p.returncode}"])[-1]
            log["docs"][key] = {"error": err, "returncode": p.returncode}
            print(f"FAIL  {key}: exit {p.returncode}: {err}", flush=True)
        log_path.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
