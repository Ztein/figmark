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
- **Context-aware descriptions.** Sends the surrounding text to the model so a
  chart is interpreted in the report's context, not just visually.
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

Produce an accessibility-annotated copy of the source PDF too:

```bash
figmark path/to/document.pdf --annotate-pdf
```

## Configuration

Everything beyond the API key is controlled by [`config.yaml`](config.yaml):

- `api.model` / `api.base_url` — which model and endpoint to use
- `description.prompt` / `diagrams.prompt` — the figure and diagram prompts
  (kept in Swedish by default; this is the product's domain output)
- `concurrency.max_workers` — parallel API calls
- `context.*` — how much surrounding text to send for context
- `ocr.language` — Tesseract language

Technical thresholds (clustering, OCR, retries, render DPI) live as documented
constants in `src/figmark/<module>.py`.

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
