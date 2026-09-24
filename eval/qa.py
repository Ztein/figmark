#!/usr/bin/env python3
"""Figure questions: can an LLM that reads only a pipeline's output answer them?
(PRD, Utvärdering → Frågor och svar, Golv, tak och normerat mått.)

A *reading* is what a pipeline made of each document: one text or Markdown file
per document at eval/runs/<reading>/<manifest>/<name>.md. For every question the
reading is chunked, the most relevant chunks are retrieved, and only those are
shown to the answerer — the way a RAG consumer would see the document. Scoring
is mechanical: right +1, "okänt" 0, wrong −1.

    uv run eval/qa.py floor                 # score the floor reading
    uv run eval/qa.py floor --ceiling       # same retrieval, plus the figure's image
    uv run eval/qa.py <reading> --repeat 2 --questions eval/questions/ppr-2026-03.yaml

Results: eval/runs/<reading>/qa-<tag>.json (every answer) and a summary on stdout.
Models and endpoints come from eval/config.yaml (see config.example.yaml).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import yaml
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
UNKNOWN = {"okänt", "okänd", "unknown", "vet ej", "vet inte"}

PROMPT = {
    "sv": {
        "system": (
            "Du besvarar frågor om ett dokument. Du ser bara utdrag ur dokumentet{img}. "
            "Svara enbart utifrån det du ser. Om det inte räcker för att avgöra svaret, svara exakt: okänt. "
            "Ett felaktigt svar är sämre än okänt. Skriv bara svaret, ingen förklaring."
        ),
        "img": " och en bild av figuren frågan gäller",
        "number": "Svara med ett tal med {d} decimaler.",
        "bool": "Svara ja eller nej.",
        "choice": "Svara med exakt ett av alternativen: {opts}.",
        "excerpts": "Utdrag",
        "question": "Fråga",
    },
    "en": {
        "system": (
            "You answer questions about a document. You only see excerpts from it{img}. "
            "Answer only from what you see. If that is not enough to decide, answer exactly: unknown. "
            "A wrong answer is worse than unknown. Write only the answer, no explanation."
        ),
        "img": " and an image of the figure the question is about",
        "number": "Answer with a number with {d} decimals.",
        "bool": "Answer yes or no.",
        "choice": "Answer with exactly one of: {opts}.",
        "excerpts": "Excerpts",
        "question": "Question",
    },
}


# ---------------------------------------------------------------- config & io


def load_config() -> dict:
    path = ROOT / "config.yaml"
    if not path.exists():
        raise SystemExit("eval/config.yaml missing — copy eval/config.example.yaml and fill it in")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def client(section: dict) -> OpenAI:
    key = os.environ.get(section.get("api_key_env", ""), "none")
    return OpenAI(base_url=section["base_url"], api_key=key, timeout=300, max_retries=4)


def load_questions(paths: list[Path]) -> list[dict]:
    out = []
    for p in paths:
        qs = yaml.safe_load(p.read_text(encoding="utf-8"))
        for fig in qs["figures"]:
            for i, q in enumerate(fig["questions"]):
                out.append(
                    {
                        **q,
                        "qid": f"{qs['document']}/{fig['id']}/{i}",
                        "manifest": qs["manifest"],
                        "document": qs["document"],
                        "language": qs.get("language", "sv"),
                        "figure": {k: fig.get(k) for k in ("id", "caption", "page", "bbox")},
                    }
                )
    return out


# ---------------------------------------------------------------- retrieval


def chunks(text: str, size: int, overlap: int) -> list[str]:
    """Pack lines into chunks of about `size` characters; each chunk repeats the
    last `overlap` characters of the previous one so nothing falls in a crack."""
    out, cur = [], ""
    for line in text.splitlines():
        if cur and len(cur) + len(line) > size:
            out.append(cur.strip())
            cur = cur[-overlap:] if overlap else ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur.strip())
    return out


class Embedder:
    def __init__(self, cfg: dict):
        self.cfg, self.api = cfg, client(cfg)
        RUNS.mkdir(exist_ok=True)
        self.db = sqlite3.connect(RUNS / "embeddings.sqlite", check_same_thread=False)
        self.db.execute("create table if not exists e (k text primary key, v blob)")
        self.lock = threading.Lock()

    def __call__(self, texts: list[str], kind: str) -> np.ndarray:
        prefix = self.cfg.get(f"{kind}_prefix", "")
        keys = [hashlib.sha1(f"{self.cfg['model']}\0{prefix}{t}".encode()).hexdigest() for t in texts]
        with self.lock:
            have = dict(self.db.execute(f"select k, v from e where k in ({','.join('?' * len(keys))})", keys))
        missing = [i for i, k in enumerate(keys) if k not in have]
        for start in range(0, len(missing), 64):
            batch = missing[start : start + 64]
            resp = self.api.embeddings.create(model=self.cfg["model"], input=[prefix + texts[i] for i in batch])
            with self.lock:
                for i, d in zip(batch, resp.data):
                    have[keys[i]] = np.asarray(d.embedding, dtype=np.float32).tobytes()
                    self.db.execute("insert or replace into e values (?, ?)", (keys[i], have[keys[i]]))
                self.db.commit()
        m = np.stack([np.frombuffer(have[k], dtype=np.float32) for k in keys])
        return m / np.linalg.norm(m, axis=1, keepdims=True)


# ---------------------------------------------------------------- answering & scoring


def figure_image(q: dict, dpi: int = 200) -> str:
    import pypdfium2 as pdfium

    pdf = ROOT / "files" / q["manifest"] / f"{q['document']}.pdf"
    page = pdfium.PdfDocument(str(pdf))[q["figure"]["page"] - 1]
    img = page.render(scale=dpi / 72).to_pil()
    if q["figure"].get("bbox"):
        x0, y0, x1, y1 = q["figure"]["bbox"]  # PDF points, top-left origin
        pad = 12
        img = img.crop(tuple(round(v * dpi / 72) for v in (x0 - pad, y0 - pad, x1 + pad, y1 + pad)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def instruction(q: dict, p: dict) -> str:
    if q["type"] == "number":
        return p["number"].format(d=q.get("decimals", 0))
    if q["type"] == "bool":
        return p["bool"]
    return p["choice"].format(opts=" | ".join(q["options"]))


def parse(q: dict, answer: str):
    a = answer.strip().strip(".*`\"' ").lower()
    if not a or a in UNKNOWN or a.startswith(("okänt", "unknown")):
        return "unknown"
    if q["type"] == "number":
        m = re.search(r"[-−–]?\s*\d[\d\s]*(?:[.,]\d+)?", a.replace(" ", " "))
        if not m:
            return None
        s = re.sub(r"\s", "", m.group()).replace("−", "-").replace("–", "-").replace(",", ".")
        return float(s)
    if q["type"] == "bool":
        if re.match(r"(ja|yes|true)\b", a):
            return True
        if re.match(r"(nej|no|false)\b", a):
            return False
        return None
    hits = [o for o in q["options"] if o.lower() == a] or [o for o in q["options"] if o.lower() in a]
    return max(hits, key=len) if hits else None


def score(q: dict, value) -> int:
    if value in ("unknown", None):
        return 0
    if q["type"] == "number":
        return 1 if abs(value - float(q["key"])) <= q.get("tolerance", 0) + 1e-9 else -1
    if q["type"] == "bool":
        return 1 if value == bool(q["key"]) else -1
    return 1 if value == str(q["key"]) else -1


# ---------------------------------------------------------------- run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reading", help="directory under eval/runs/")
    ap.add_argument("--questions", nargs="+", type=Path, default=sorted((ROOT / "questions").glob("*.yaml")))
    ap.add_argument("--ceiling", action="store_true", help="also show the figure's image")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    cfg = load_config()
    ans_cfg, ret = cfg["answerer"], cfg["retrieval"]
    answerer, embed = client(ans_cfg), Embedder(cfg["embedder"])
    questions = load_questions(args.questions)
    base = RUNS / args.reading

    # retrieve once per question; the chunks are identical across repeats
    docs: dict[str, tuple[list[str], np.ndarray]] = {}
    for q in questions:
        key = f"{q['manifest']}/{q['document']}"
        if key not in docs:
            text = (base / q["manifest"] / f"{q['document']}.md").read_text(encoding="utf-8")
            cs = chunks(text, ret["chunk_chars"], ret["overlap_chars"])
            docs[key] = (cs, embed(cs, "passage"))
    qvec = embed([q["q"] for q in questions], "query")
    for q, v in zip(questions, qvec):
        cs, m = docs[f"{q['manifest']}/{q['document']}"]
        top = np.argsort(-(m @ v))[: ret["top_k"]]
        q["context"] = [cs[i] for i in sorted(top)]  # document order reads more naturally

    def ask(q: dict, rep: int) -> dict:
        p = PROMPT[q["language"]]
        text = (
            f"{p['excerpts']}:\n\n" + "\n\n---\n\n".join(q["context"])
            + f"\n\n{p['question']}: {q['q']}\n{instruction(q, p)}"
        )
        content: list[dict] = [{"type": "text", "text": text}]
        if args.ceiling:
            content.insert(0, {"type": "image_url", "image_url": {"url": q["image"]}})
        t0 = time.time()
        r = answerer.chat.completions.create(
            model=ans_cfg["model"],
            temperature=0,
            seed=rep,
            max_tokens=40,
            messages=[
                {"role": "system", "content": p["system"].format(img=p["img"] if args.ceiling else "")},
                {"role": "user", "content": content},
            ],
            **ans_cfg.get("extra", {}),
        )
        raw = r.choices[0].message.content or ""
        value = parse(q, raw)
        return {"qid": q["qid"], "repeat": rep, "raw": raw, "value": value, "score": score(q, value),
                "invalid": value is None, "seconds": round(time.time() - t0, 2)}

    if args.ceiling:  # pdfium is not thread-safe: render every figure up front
        images: dict[str, str] = {}
        for q in questions:
            k = f"{q['document']}/{q['figure']['id']}"
            q["image"] = images[k] = images.get(k) or figure_image(q)

    jobs = [(q, rep) for rep in range(args.repeat) for q in questions]
    with ThreadPoolExecutor(ans_cfg.get("parallel", 8)) as pool:
        results = list(pool.map(lambda j: ask(*j), jobs))

    per_rep = []
    for rep in range(args.repeat):
        rs = [r for r in results if r["repeat"] == rep]
        per_rep.append({
            "score": sum(r["score"] for r in rs), "n": len(rs),
            "right": sum(r["score"] == 1 for r in rs), "wrong": sum(r["score"] == -1 for r in rs),
            "unknown": sum(r["value"] == "unknown" for r in rs), "invalid": sum(r["invalid"] for r in rs),
        })
    tag = args.tag or ("ceiling" if args.ceiling else "reading")
    out = {
        "reading": args.reading, "mode": "ceiling" if args.ceiling else "reading", "tag": tag,
        "answerer": ans_cfg["model"], "embedder": cfg["embedder"]["model"], "retrieval": ret,
        "questions": [str(p.relative_to(ROOT)) for p in args.questions],
        "summary": per_rep,
        "questions_detail": [{k: q[k] for k in ("qid", "q", "type", "key", "context")} for q in questions],
        "answers": results,
    }
    (base / f"qa-{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for i, s in enumerate(per_rep):
        print(f"{args.reading} [{tag}] run {i}: score {s['score']:+d}/{s['n']}  right {s['right']}  "
              f"unknown {s['unknown']}  wrong {s['wrong']}  invalid {s['invalid']}")


if __name__ == "__main__":
    main()
