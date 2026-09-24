#!/usr/bin/env python3
"""Draw test set v1 from the inventory (PRD, Utvärdering → Stratifiera, Frys).

The rules are fixed here so the draw can be repeated and argued with; the
output eval/testset-v1.yaml is frozen once committed. A new draw is a new
version, never an edit.

    uv run eval/testset.py        # writes eval/testset-v1.yaml unless it exists
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "testset-v1.yaml"
RARE = {"flow_chart", "geographical_map", "pie_chart"}  # a few dozen in the whole corpus; take every document that has one
V1_FORMATS = {"pdf", "docx", "pptx"}  # PRD goal 1: other formats wait for phase 4


def classes(row: dict) -> Counter:
    return Counter({c: int(n) for c, n in (kv.rsplit(":", 1) for kv in row["classes"].split())})


def draw(rows: list[dict]) -> list[tuple[dict, str]]:
    picked: list[tuple[dict, str]] = []
    asked = {yaml.safe_load(p.read_text(encoding="utf-8"))["document"] for p in (ROOT / "questions").glob("*.yaml")}
    for r in rows:
        if r["format"] not in V1_FORMATS or r["error"]:
            continue
        m, name, cls = r["manifest"], r["name"], classes(r)
        if name in asked:
            picked.append((r, "has figure questions"))
        elif m == "papers":
            picked.append((r, "academic figures"))
        elif m == "office":
            if int(r["figures"] or 0) or int(r["charts_xml"] or 0) or int(r["smartart"] or 0):
                picked.append((r, "native figures: images, chart XML or SmartArt"))
            elif r["format"] == "docx":
                picked.append((r, "native text only: text and tracked-change truth"))
        elif m == "central-banks":
            rare = sorted(set(cls) & RARE)
            if rare:
                picked.append((r, "rare figure types: " + ", ".join(rare)))
    # every central-bank publisher at least once: its first report in the manifest
    have = {r["name"].split("-")[0] for r, _ in picked if r["manifest"] == "central-banks"}
    for r in rows:
        pub = r["name"].split("-")[0]
        if r["manifest"] == "central-banks" and pub not in have:
            picked.append((r, f"publisher coverage: {pub}"))
            have.add(pub)
    # Riksbank PPR: the last full report of every year, plus two updates (short format)
    ppr = [r for r in rows if r["manifest"] == "riksbank-ppr"]
    last = {}
    for r in ppr:
        if r["name"].startswith("ppr-"):
            last[r["name"][4:8]] = r
    for year, r in sorted(last.items()):
        if r["name"] not in asked:
            picked.append((r, f"Riksbank PPR, one per year ({year})"))
    for r in [r for r in ppr if r["name"].startswith("ppu-")][::5]:
        picked.append((r, "Riksbank PPR update, short format"))
    return picked


def main() -> None:
    if OUT.exists() and "--force" not in sys.argv:
        raise SystemExit(f"{OUT.name} exists and is frozen; draw a new version instead")
    rows = list(csv.DictReader(open(ROOT / "inventory.csv", encoding="utf-8")))
    picked = draw(rows)
    docs = [
        {"manifest": r["manifest"], "name": r["name"], "format": r["format"], "language": r["language"],
         "pages": int(r["pages"] or 0), "figures": int(r["figures"] or 0), "why": why}
        for r, why in picked
    ]
    strata = {
        "documents": len(docs),
        "pages": sum(d["pages"] for d in docs),
        "figures (detected or embedded)": sum(d["figures"] for d in docs),
        "formats": dict(Counter(d["format"] for d in docs)),
        "languages": dict(Counter(d["language"] for d in docs)),
        "scanned": 0,
    }
    header = (
        "# Test set v1 — FROZEN. Drawn by eval/testset.py from eval/inventory.csv.\n"
        "# Change nothing here; new documents go into a new version.\n"
        "# Gap: no scanned documents in the evaluation corpus yet (PRD asks for them).\n"
    )
    OUT.write_text(header + yaml.safe_dump({"strata": strata, "documents": docs}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(yaml.safe_dump(strata, allow_unicode=True, sort_keys=False))


if __name__ == "__main__":
    main()
