# figmark

[![CI](https://github.com/joelstenberg/figmark/actions/workflows/ci.yml/badge.svg)](https://github.com/joelstenberg/figmark/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**Turn a PDF into Markdown where every figure is described, not dropped.**

figmark extracts a PDF's text and replaces each image and vector diagram with an
AI-generated description, producing one coherent Markdown document. Think Docling,
but with first-class figure interpretation: charts, photos, and diagrams become
readable prose in reading order instead of vanishing.

It was built to produce accessible alt text in formal Swedish
("myndighetssvenska"), but works against **any OpenAI-compatible vision endpoint**
— [Berget.ai](https://berget.ai) is the default, not a requirement.

## What it does

- **Text + figures → Markdown.** Output is a single `<name>.md` with figures
  embedded as `![...](images/…)` followed by their description as a caption.
- **Vector diagram detection.** Matplotlib-style charts (which `get_images()`
  misses) are found by clustering vector drawings, rendered, and described with a
  diagram-specific prompt.
- **Scanned PDFs.** Falls back to OCR — Tesseract first, a vision model when
  Tesseract's quality is too low.
- **Context-aware descriptions.** Sends the surrounding text — plus a one-line
  summary of what kind of document it is — to the model, so a chart is interpreted
  in the report's context, not just visually.
- **Matches the document's language.** Descriptions follow the document's own
  language by default (auto-detected), or you can force one — so an English PDF
  gets English captions, not Swedish ones.
- **Skips decorative images.** A significance gate lets the model leave out
  logos, dividers, and icons that carry no information — no extra API calls.
- **Parallel + cached.** Descriptions run concurrently and are cached on disk; a
  second run re-uses them and makes no API calls.
- **Fail loudly.** No silent fallbacks — strategy switches are shouted with clear
  `!!!` banners.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

For scanned PDFs you also need Tesseract:

```bash
# macOS
brew install tesseract tesseract-lang
# Debian/Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-swe
```

Set your API key:

```bash
cp .env.example .env
# edit .env and set BERGET_API_KEY
```

## Usage

```bash
figmark path/to/document.pdf
```

Output lands in `output/<pdf-name>/`:

- `<pdf-name>.md` — **the primary output**: text with figure descriptions inlined
- `raw_text.txt` — text only, no descriptions
- `images/`, `diagrams/` — extracted figures
- `descriptions/`, `diagram_descriptions/` — one `.txt` per figure (the cache)
- `document_summary.txt`, `document_language.txt` — cached document-level context

Produce an accessibility-annotated copy of the source PDF too:

```bash
figmark path/to/document.pdf --annotate-pdf
```

## Run as a service (container)

figmark also ships as a hardened HTTP service for air-gapped deployment — a
single container that needs only a reachable OpenAI-compatible vision endpoint.

```bash
mkdir -p secrets
printf '%s' 'a-strong-token' > secrets/auth_token
printf '%s' "$BERGET_API_KEY" > secrets/berget_api_key
docker compose up -d            # builds/loads the image, starts figmark-server

curl -s -X POST http://127.0.0.1:8000/v1/convert \
  -H "Authorization: Bearer a-strong-token" \
  -F "file=@document.pdf;type=application/pdf"
```

The image is non-root, read-only-rootfs compatible, self-contained (Tesseract +
language data baked in), and passes a hard Trivy scan in CI. Secrets come from
files (never the image or plaintext env). Full runbook:
[docs/deployment.md](docs/deployment.md); security model: [SECURITY.md](SECURITY.md).

## Configuration

Everything beyond the API key is controlled by [`config.yaml`](config.yaml):

- `api.model` / `api.base_url` — which model and endpoint to use
- `language.output` — output language for descriptions/diagrams/summary:
  `auto` follows the document's own language, or name one (`Swedish`, `English`)
  to force it
- `description.prompt` / `diagrams.prompt` — the figure and diagram prompts
  (written in Swedish by default; they set the task and register, the output
  language is controlled separately by `language.output`)
- `concurrency.max_workers` — parallel API calls
- `context.*` — how much surrounding text to send for context
- `significance.enabled` — let the model skip purely decorative images
- `document_summary.*` — generate a document-type summary and pass it as context
- `ocr.language` — Tesseract language

Technical thresholds (clustering, OCR, retries, render DPI) live as documented
constants in `src/figmark/<module>.py`.

## How it works

A PDF is classified as text-encoded or scanned, its text is extracted (or OCR'd),
images and vector diagrams are found, the document's language and a short summary
are determined, and every figure is described in parallel and woven back into the
text in reading order. For the full pipeline, module map, and outputs, see
**[docs/architecture.md](docs/architecture.md)**.

## Tests

```bash
pytest -m "not live"   # fast, offline, no API key
pytest -m "live"       # against the real API (costs money, takes minutes)
pytest                 # everything
```

See [examples/README.md](examples/README.md) for sample documents.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

## Roadmap

- **0.2 — configurable pipeline.** Per-task provider/model selection (a different
  model for image description, diagram description, and vision-OCR) via a
  `providers` / `tasks` config, plus all technical knobs exposed in config.

## License

[MIT](LICENSE)
