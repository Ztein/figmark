#!/usr/bin/env python3
"""Compare readings on the questions: floor, candidates, ceiling (PRD, Golv, tak och normerat mått).

    uv run eval/report.py floor docling-plain docling

Reads eval/runs/<reading>/qa-reading.json for every reading and the ceiling from
eval/runs/floor/qa-ceiling.json. Questions are grouped by what they ask about —
figure, table or text — and each group gets the mean score per question
(right +1, unknown 0, wrong −1) and the coverage (reading − floor) / (ceiling −
floor). A 95 % bootstrap interval over questions is given for each difference
to the floor. Also prints throughput from each reading's run.json.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"


def groups() -> dict[str, str]:
    out = {}
    for p in sorted((ROOT / "questions").glob("*.yaml")):
        qs = yaml.safe_load(p.read_text(encoding="utf-8"))
        for f in qs["figures"]:
            kind = f.get("kind", "chart")
            group = kind if kind in ("text", "table") else "figure"
            for i in range(len(f["questions"])):
                out[f"{qs['document']}/{f['id']}/{i}"] = group
    return out


def scores(path: Path) -> dict[str, float]:
    per: dict[str, list[int]] = {}
    for a in json.loads(path.read_text(encoding="utf-8"))["answers"]:
        per.setdefault(a["qid"], []).append(a["score"])
    return {q: sum(s) / len(s) for q, s in per.items()}


def ci(diffs: list[float], n: int = 2000) -> tuple[float, float]:
    rng = random.Random(0)
    ms = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def main(readings: list[str]) -> None:
    grp = groups()
    s = {r: scores(RUNS / r / "qa-reading.json") for r in readings}
    s["ceiling"] = scores(RUNS / "floor" / "qa-ceiling.json")
    floor = s[readings[0]]
    for g in ("figure", "table", "text"):
        qids = [q for q in floor if grp.get(q) == g and all(q in v for v in s.values())]
        if not qids:
            continue
        mean = {r: sum(v[q] for q in qids) / len(qids) for r, v in s.items()}
        gap = mean["ceiling"] - mean[readings[0]]
        print(f"\n### {g} questions ({len(qids)})\n")
        print("| Reading | Mean score | Coverage | Δ vs floor, 95 % CI |\n| --- | --- | --- | --- |")
        for r in [*readings, "ceiling"]:
            cov = (mean[r] - mean[readings[0]]) / gap if gap > 0.05 else float("nan")
            lo, hi = ci([s[r][q] - floor[q] for q in qids]) if r != readings[0] else (0.0, 0.0)
            print(f"| {r} | {mean[r]:+.3f} | {cov:.0%} | [{lo:+.3f}, {hi:+.3f}] |")
    print("\n| Reading | Documents | Errors | Pages | Figures | Described | Seconds | Pages/min |\n| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in readings:
        log = RUNS / r / "run.json"
        if not log.exists():
            continue
        docs = json.loads(log.read_text(encoding="utf-8"))["docs"].values()
        ok = [d for d in docs if "error" not in d]
        pages, secs = sum(d["pages"] for d in ok), sum(d["seconds"] for d in ok)
        print(f"| {r} | {len(ok) + (len(docs) - len(ok))} | {len(docs) - len(ok)} | {pages} | "
              f"{sum(d['figures'] for d in ok)} | {sum(d['described'] for d in ok)} | {secs:.0f} | {60 * pages / secs:.1f} |")


if __name__ == "__main__":
    main(sys.argv[1:] or ["floor", "docling-plain", "docling"])
