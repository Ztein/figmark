# figmark

[![CI](https://github.com/Ztein/figmark/actions/workflows/ci.yml/badge.svg)](https://github.com/Ztein/figmark/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**Turn a PDF into Markdown where every figure is described, not dropped.**

figmark extracts a PDF's text and replaces each image and vector diagram with an
AI-generated description, producing one coherent Markdown document. Think Docling,
but with first-class figure interpretation: charts, photos, and diagrams become
readable prose in reading order instead of vanishing.

It was built to produce accessible alt text in formal Swedish
("myndighetssvenska"). **You need a vision-capable model behind an
OpenAI-compatible API** — hosted or local (e.g. vLLM or Ollama). Point
`api.base_url` / `api.model` in `config.yaml` at your endpoint and put its key
in `FIGMARK_API_KEY` (the variable name is historical; a provider-neutral name
is tracked in [T-010](docs/tickets/T-010-provider-agnostic-llm-key.md)).

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

Point figmark at your endpoint and set your API key:

```bash
cp config.example.yaml config.yaml
# edit config.yaml: api.base_url + api.model (your OpenAI-compatible endpoint)

cp .env.example .env
# edit .env and set FIGMARK_API_KEY (or FIGMARK_API_KEY=none for keyless local endpoints)
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

Prebuilt images are published to GHCR — every green build of `main` as `:edge`,
and releases as `:<version>` + `:latest`:

```bash
docker pull ghcr.io/ztein/figmark:edge
```

Or run the stack with compose (no source checkout needed — just `compose.yaml`
and a config):

```bash
cp config.example.yaml config.yaml   # edit api.base_url + api.model
mkdir -p secrets
printf '%s' 'a-strong-token' > secrets/auth_token
printf '%s' "$FIGMARK_API_KEY" > secrets/figmark_api_key
docker compose up -d                  # pulls ghcr.io/ztein/figmark:edge

curl -s -X POST http://127.0.0.1:8000/v1/convert \
  -H "Authorization: Bearer a-strong-token" \
  -F "file=@document.pdf;type=application/pdf"
```

Unlike the CLI (which writes files — `<name>.md`, `figures.json`, …), the HTTP
surface returns everything **inline as JSON**:

| Field | Meaning |
|---|---|
| `markdown` | the converted document (with `<!-- page N -->` markers for provenance) |
| `page_count` / `figure_count` / `skipped_count` | pages processed, figures described, images skipped by the significance gate |
| `language` | detected document language |
| `usage` | `prompt_tokens`, `completion_tokens`, `total_tokens`, `api_calls`, `calls_missing_usage` |
| `estimated_cost` / `currency` | monetary estimate — **`null` unless both token prices are set** in `config.yaml` (never a misleading `0`) |

Health/metadata endpoints are auth-free: `GET /readyz` and `GET /version`.

The image is non-root, read-only-rootfs compatible, self-contained (Tesseract +
language data baked in), and passes a hard Trivy scan in CI. Secrets come from
files (never the image or plaintext env). Full runbook:
[docs/deployment.md](docs/deployment.md); security model: [SECURITY.md](SECURITY.md).

## Configuration

Everything beyond the API key is controlled by your `config.yaml` (start from
[`config.example.yaml`](config.example.yaml)):

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

A PDF is classified as text-encoded or scanned and its text extracted (or OCR'd),
then given structure (headings/lists inferred from typography), ruled tables
reconstructed as Markdown, running headers/footers stripped, hyperlinks preserved,
and images + vector diagrams found and described in parallel — all woven back into
the text in column-aware reading order. A `figures.json` indexes every figure. For
the full pipeline, module map, outputs, and the open Phase-2 items, see
**[docs/architecture.md](docs/architecture.md)**.

## Known limitations

- **Broken text layers.** figmark trusts the PDF's embedded text. A PDF with a
  missing or broken font encoding (no/garbled ToUnicode CMap) can carry plenty of
  characters that are actually mojibake; figmark extracts them as-is. It does not
  silently swallow this — pages whose text looks broken are flagged with a loud
  warning — but it does not yet auto-OCR them. For such files, re-export from the
  source or pre-OCR them before converting.
- **Tables.** Ruled data tables are reconstructed as Markdown behind a conservative
  filter (`docs/tickets/T-031`). Quantitative data drawn as a *chart* is captured by
  the figure description instead. **Borderless / whitespace-aligned tables** (e.g.
  forecast appendices with no ruling lines) are *not* detected and fall through to
  the text path, where they are **flattened**: row labels and cell values land on
  separate lines and column headers can detach, so the column↔value link is lost in
  the raw text (`docs/tickets/T-050`). The data is all still present, and a
  downstream LLM can often recover it — the preserved `<!-- page N -->` markers let
  you point a model (or a reader) at the source page. This is deliberate: forcing
  detection on these pages (PyMuPDF's whitespace strategy) does find a grid, but
  mis-aligns its columns — chopping labels and splitting numbers — so it would emit
  a table asserting the *wrong* column↔value mapping, which is worse than honest
  flat text. We keep the raw text rather than guess a structure. For
  number-critical lookups over such documents, treat tables as a known gap.
- **Footnotes.** Footnote text is kept (in reading order, at the page bottom) but
  not yet segregated/marked as footnotes (`docs/tickets/T-044`, Phase 2).
- **Tagged PDF.** `--tagged-pdf` writes the structure-tree *foundation* (figure
  `/Alt`); full PDF/UA conformance is not yet claimed (`docs/tickets/T-004`).

## Tests

```bash
pytest -m "not live and not docker"   # fast, offline, no API key, no Docker
pytest -m docker                       # builds the image + runs the compose stack
pytest -m "live"                       # against the real API (costs money, takes minutes)
pytest                                 # everything
```

See [examples/README.md](examples/README.md) for sample documents.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

## Roadmap

- **0.2 — configurable pipeline.** Per-task provider/model selection (a different
  model for image description, diagram description, and vision-OCR) via a
  `providers` / `tasks` config, plus all technical knobs exposed in config.
- **Document model + more formats.** A typed block model
  (`heading`/`paragraph`/`list`/`table`/`figure`) that PDF maps into and Markdown
  renders out of (`docs/tickets/T-042`), so the same structure work carries over to
  Word/Excel/PowerPoint inputs.

## License

[MIT](LICENSE)
