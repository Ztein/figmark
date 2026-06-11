#!/usr/bin/env python3
"""Run the evaluation corpus through the figmark pipeline and collect stats.

For every document in examples/eval/manifest.yaml (downloaded via
download_eval.py), runs the full conversion and records page count, described/
skipped figures, detected language, duration, and any error into
output/eval/results.json (written incrementally, so progress can be monitored).

Figure descriptions are cached on disk per document (output/eval/<name>/), so
re-runs only pay for what hasn't been described yet.

Usage:
    python examples/run_eval.py            # all documents
    python examples/run_eval.py name1 ...  # a subset
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from figmark.config import load_config  # noqa: E402
from figmark.describe import make_client  # noqa: E402
from figmark.pipeline import convert  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "examples" / "eval"
OUT_ROOT = ROOT / "output" / "eval"
RESULTS = OUT_ROOT / "results.json"
# Two documents at a time; each conversion runs its own describe workers.
DOC_CONCURRENCY = 2


def run_one(doc: dict, cfg) -> dict:
    name = doc["name"]
    pdf = EVAL_DIR / f"{name}.pdf"
    start = time.time()
    try:
        result = convert(pdf, cfg, OUT_ROOT, client=make_client(cfg), quiet=True)
        return {
            "name": name,
            "source": doc["source"],
            "expected_language": doc["language"],
            "ok": True,
            "pages": result.page_count,
            "figures": result.figure_count,
            "skipped": result.skipped_count,
            "language": result.language,
            "seconds": round(time.time() - start, 1),
        }
    except Exception as e:  # noqa: BLE001 — the eval must survive a bad document
        return {
            "name": name,
            "source": doc["source"],
            "expected_language": doc["language"],
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "seconds": round(time.time() - start, 1),
        }


def main() -> int:
    manifest = yaml.safe_load((EVAL_DIR / "manifest.yaml").read_text(encoding="utf-8"))
    docs = manifest["documents"]
    if len(sys.argv) > 1:
        wanted = set(sys.argv[1:])
        docs = [d for d in docs if d["name"] in wanted]
    missing = [d["name"] for d in docs if not (EVAL_DIR / f"{d['name']}.pdf").exists()]
    if missing:
        print(f"Missing PDFs (run download_eval.py): {missing}", file=sys.stderr)
        return 1

    cfg = load_config(ROOT / "config.yaml")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    print(f"Evaluating {len(docs)} documents ({DOC_CONCURRENCY} concurrently) …", flush=True)
    with ThreadPoolExecutor(max_workers=DOC_CONCURRENCY) as pool:
        futures = {pool.submit(run_one, d, cfg): d["name"] for d in docs}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            status = (
                f"ok  {r['pages']:>3}p {r['figures']:>3} fig ({r['skipped']} skipped) "
                f"{r['language']:<10}"
                if r["ok"]
                else f"FAILED: {r['error'][:80]}"
            )
            print(
                f"[{len(results):>2}/{len(docs)}] {r['name']:<22} {status} {r['seconds']}s",
                flush=True,
            )
            RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    failed = [r for r in results if not r["ok"]]
    print(f"\nDone: {len(results) - len(failed)} ok, {len(failed)} failed → {RESULTS}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
