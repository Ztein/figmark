#!/usr/bin/env python3
"""H0: does the yardstick tell good output from bad? (PRD, Validera måttstocken först.)

For every figure that has a reference description in eval/h0/reference/<document>/
<figure-id>.md, build readings of known quality and score them with qa.py:

    reference      the reference description (strong model from another family
                   than the figure interpreter, written without seeing the questions)
    wrong_numbers  the same text with every value changed (years kept)
    swapped        structure broken: flowchart edges reversed (step list dropped),
                   chart series names rotated
    ocr_only       only the text inside the figure's box (text layer, else Tesseract)
    none           nothing added — identical to the floor

Each reading is the floor text with the variant inserted where the figure stands.

    uv run eval/h0.py build          # write eval/runs/h0-<variant>/
    uv run eval/h0.py crops          # figure crops to eval/runs/crops/ (for writing references)
    uv run eval/h0.py report         # after qa.py has scored each reading
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pypdfium2 as pdfium
import yaml

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
REF = ROOT / "h0" / "reference"
VARIANTS = ["reference", "wrong_numbers", "swapped", "ocr_only", "none"]
YEAR = re.compile(r"^(19|20)\d\d$")


def figures() -> list[dict]:
    out = []
    for p in sorted((ROOT / "questions").glob("*.yaml")):
        qs = yaml.safe_load(p.read_text(encoding="utf-8"))
        for f in qs["figures"]:
            ref = REF / qs["document"] / f"{f['id']}.md"
            if ref.exists():
                out.append({**f, "manifest": qs["manifest"], "document": qs["document"], "reference": ref.read_text(encoding="utf-8").strip()})
    return out


# ---------------------------------------------------------------- degradations


LABEL = re.compile(r"(?:Diagram|Figur|Figure|Chart|Tabell|Table)\s+$", re.I)


def wrong_numbers(text: str) -> str:
    """Move every value by 30–60 % (deterministic per value); leave years and figure numbers alone."""

    def change(m: re.Match) -> str:
        s = m.group()
        if YEAR.match(s) or LABEL.search(text[max(0, m.start() - 10) : m.start()]):
            return s
        v = float(s.replace(",", "."))
        h = int(hashlib.sha1(s.encode()).hexdigest(), 16)
        factor = (1.3 + (h % 31) / 100) if h % 2 else (0.7 - (h % 31) / 100)
        new = v * factor if v else (h % 5) + 1.0
        dec = len(s.split(",")[-1]) if "," in s else len(s.split(".")[-1]) if "." in s else 0
        out = f"{new:.{dec}f}"
        return out.replace(".", ",") if "," in s else out

    return re.sub(r"\d+(?:[.,]\d+)?", change, text)


NODE = re.compile(r"\b([A-Za-z]\w*)\s*(\[\[.*?\]\]|\[.*?\]|\{.*?\}|\(\(.*?\)\)|\(.*?\))")
EDGE = re.compile(r"^(\s*)(\w+)\s*(-->|-\.->|==>)\s*(\|[^|]*\|)?\s*(\w+)\s*$")


def reverse_mermaid(block: str) -> str:
    """Every one-way edge points the other way; node labels stay on their nodes."""
    decls, lines = {}, []
    for line in block.splitlines():
        bare = NODE.sub(lambda m: decls.setdefault(m.group(1), m.group(0)) and m.group(1), line)
        e = EDGE.match(bare)
        lines.append(f"{e.group(1)}{e.group(5)} {e.group(3)}{e.group(4) or ''} {e.group(2)}" if e else bare)
    head, body = lines[0], lines[1:]
    return "\n".join([head] + [f"  {d}" for d in decls.values()] + [ln for ln in body if ln.strip() not in decls])


def swapped(text: str) -> str:
    """Flowcharts: every edge reversed, the step list dropped (it would restate the
    true order). Charts: series names rotated, so values sit under the wrong series."""
    m = re.search(r"```mermaid\n(.*?)```", text, flags=re.S)
    if m:
        return text[: m.start()] + "```mermaid\n" + reverse_mermaid(m.group(1).rstrip()) + "\n```\n"
    names = re.findall(r"^\s*[-*]\s*\*\*([^*]+)\*\*", text, flags=re.M)
    if len(names) < 2:
        return text
    rotated = dict(zip(names, names[1:] + names[:1]))
    return re.sub(r"\*\*([^*]+)\*\*", lambda m: f"**{rotated.get(m.group(1), m.group(1))}**", text)


def ocr_only(f: dict) -> str:
    pdf = pdfium.PdfDocument(str(ROOT / "files" / f["manifest"] / f"{f['document']}.pdf"))
    page = pdf[f["page"] - 1]
    x0, y0, x1, y1 = f["bbox"]
    h = page.get_height()
    text = page.get_textpage().get_text_bounded(left=x0, bottom=h - y1, right=x1, top=h - y0)
    if len(text.strip()) >= 20:
        return " ".join(text.split())
    img = page.render(scale=300 / 72).to_pil().crop(tuple(round(v * 300 / 72) for v in (x0, y0, x1, y1)))
    png = RUNS / "crops" / "ocr-tmp.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    img.save(png)
    out = subprocess.run(["tesseract", str(png), "-", "-l", "swe+eng"], capture_output=True, text=True, check=True)
    return " ".join(out.stdout.split())


# ---------------------------------------------------------------- readings


def block(f: dict, body: str) -> str:
    return (
        f"<!-- figure id={f['id']} page={f['page']} origin=interpreted -->\n"
        f"**{f['caption']} (s. {f['page']}).** Tolkad figur.\n\n{body}\n"
    )


def insert(text: str, f: dict, body: str) -> str:
    """Put the block right after the figure's caption on its page, or at the page's end."""
    pages = re.split(r"(?=^--- Sida \d+ ---$)", text, flags=re.M)
    for i, p in enumerate(pages):
        if p.startswith(f"--- Sida {f['page']} ---"):
            lines = p.split("\n")
            head = re.match(r"\S+\s+(?:[A-Z](?:\.\d+)?|\d+(?:\.\d+)?)\b", f["caption"]).group()  # "Diagram 39", "Figure B.1"
            label = re.compile(rf"^\s*{re.escape(head)}(?!\d|\.\d)")
            at = next((j + 1 for j, line in enumerate(lines) if label.match(line)), len(lines))
            pages[i] = "\n".join(lines[:at] + ["", block(f, body)] + lines[at:])
            return "".join(pages)
    raise ValueError(f"page {f['page']} not in floor text of {f['document']}")


def build() -> None:
    figs = figures()
    for variant in VARIANTS:
        docs: dict[tuple[str, str], str] = {}
        for f in figs:
            key = (f["manifest"], f["document"])
            text = docs.get(key) or (RUNS / "floor" / f["manifest"] / f"{f['document']}.md").read_text(encoding="utf-8")
            body = {
                "reference": lambda: f["reference"],
                "wrong_numbers": lambda: wrong_numbers(f["reference"]),
                "swapped": lambda: swapped(f["reference"]),
                "ocr_only": lambda: ocr_only(f),
                "none": lambda: None,
            }[variant]()
            docs[key] = insert(text, f, body) if body else text
        for (manifest, name), text in docs.items():
            dest = RUNS / f"h0-{variant}" / manifest / f"{name}.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        print(f"ok    h0-{variant}: {len(figs)} figures")


def crops() -> None:
    sys.path.insert(0, str(ROOT))
    import base64

    from qa import figure_image

    for p in sorted((ROOT / "questions").glob("*.yaml")):
        qs = yaml.safe_load(p.read_text(encoding="utf-8"))
        for f in qs["figures"]:
            q = {"manifest": qs["manifest"], "document": qs["document"], "figure": f}
            dest = RUNS / "crops" / qs["document"] / f"{f['id']}.png"
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(base64.b64decode(figure_image(q).split(",", 1)[1]))
            print(dest.relative_to(ROOT))


def report() -> None:
    import random

    runs = {}
    for v in VARIANTS + ["ceiling"]:
        path = RUNS / ("floor/qa-ceiling.json" if v == "ceiling" else f"h0-{v}/qa-reading.json")
        if path.exists():
            runs[v] = json.loads(path.read_text(encoding="utf-8"))
    per_q = {v: {} for v in runs}
    for v, r in runs.items():
        for a in r["answers"]:
            per_q[v].setdefault(a["qid"], []).append(a["score"])
    floor = json.loads((RUNS / "floor" / "qa-reading.json").read_text(encoding="utf-8"))
    solved = {q for q in {a["qid"] for a in floor["answers"]}
              if all(a["score"] == 1 for a in floor["answers"] if a["qid"] == q)}
    only = sys.argv[2] if len(sys.argv) > 2 else "figure"  # figure | all | <kind>
    kinds = {f"{f['document']}/{f['id']}": f.get("kind", "chart") for f in figures()}
    qids = sorted(q for q in per_q["none"] if (only == "all" or q not in solved)
                  and (only in ("all", "figure") or kinds[q.rsplit("/", 1)[0]] == only))
    print(f"subset: {only} ({len(solved & set(per_q['none']))} questions the floor answers without the figure excluded)"
          if only != "all" else "subset: all")
    for v in per_q:
        per_q[v] = {q: s for q, s in per_q[v].items() if q in qids}
    mean = lambda v: sum(sum(s) / len(s) for s in per_q[v].values()) / len(qids)  # noqa: E731

    def boot(a: str, b: str, n: int = 2000) -> tuple[float, float]:
        rng = random.Random(0)
        d = [sum(per_q[a][q]) / len(per_q[a][q]) - sum(per_q[b][q]) / len(per_q[b][q]) for q in qids]
        ms = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(n))
        return ms[int(0.025 * n)], ms[int(0.975 * n)]

    print(f"{len(qids)} questions; score per question, right +1 / unknown 0 / wrong −1\n")
    print("| Variant | Mean score | Per run |\n| --- | --- | --- |")
    for v in runs:
        reps = max(len(s) for s in per_q[v].values())
        per_run = [sum(per_q[v][q][k] for q in qids) for k in range(reps)]
        print(f"| {v} | {mean(v):+.3f} | {', '.join(f'{x:+d}' for x in per_run)} of {len(qids)} |")
    print("\n| Comparison | Difference | 95 % CI (bootstrap over questions) |\n| --- | --- | --- |")
    for a, b in [("reference", "none"), ("reference", "wrong_numbers"), ("reference", "swapped"),
                 ("reference", "ocr_only"), ("ocr_only", "none"), ("ocr_only", "wrong_numbers"),
                 ("ceiling", "reference")]:
        if a in runs and b in runs:
            lo, hi = boot(a, b)
            print(f"| {a} − {b} | {mean(a) - mean(b):+.3f} | [{lo:+.3f}, {hi:+.3f}] |")


if __name__ == "__main__":
    {"build": build, "crops": crops, "report": report}[sys.argv[1]]()
