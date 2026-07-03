# figmark

[![CI](https://github.com/Ztein/figmark/actions/workflows/ci.yml/badge.svg)](https://github.com/Ztein/figmark/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/figmark)](https://pypi.org/project/figmark/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**Turn a document into Markdown where every figure is described, not dropped.**

figmark extracts a document's text and replaces each image and vector diagram
with an AI-generated description, producing one coherent Markdown document.
Think Docling, but with first-class figure interpretation: charts, photos, and
diagrams become readable prose in reading order instead of vanishing.

**You need a vision-capable model behind an OpenAI-compatible API** — hosted or
local (e.g. vLLM or Ollama). Point `api.base_url` / `api.model` in `config.yaml`
at your endpoint and put its key in `FIGMARK_API_KEY` (the variable name is
historical; a provider-neutral name is tracked in
[T-010](docs/tickets/T-010-provider-agnostic-llm-key.md)).

## What figmark is for

figmark exists to extract **as much valuable information from a document as
possible, in a form LLM-based products can use effectively** — RAG ingestion,
a document dropped into an assistant's chat context, or an OCR backend for a
platform like LibreChat. It speaks the Mistral-OCR wire format
(`/v1/ocr`) so those products can point at it unchanged — and aims to do the
job *better* than plain OCR by also interpreting the parts of a document that
text extraction alone cannot see: charts, diagrams, photos, and other figures
that carry information.

Three consequences of that goal shape the design:

- **Extraction quality is a spectrum, not a binary.** Plain text extraction
  already gets a downstream LLM most of the way; every figure description,
  reconstructed table, and inferred heading on top of that makes the
  representation better. Partial information about a chart is far more valuable
  than no information — a downstream LLM is forgiving and works well with an
  imperfect but honest representation. figmark therefore never withholds the
  text just because a richer structure could not be recovered, and never
  asserts structure it isn't sure of (see the table notes under Known
  limitations).
- **Figure interpretation is the differentiator.** Anything that would drop a
  chart or image that carries meaning — a text-only extractor, a converter that
  rasterises figures away — defeats the purpose. This is why Office documents
  go through a full-fidelity conversion rather than a lightweight text
  extractor (T-054).
- **OCR of scans is a supporting capability, not the product.** figmark handles
  scanned pages (Tesseract, with a vision-model rescue) so mixed corpora don't
  fail, but it is not built for large-scale OCR of scanned archives — for
  born-digital, figure-bearing documents it shines; for messy scans a dedicated
  VLM-OCR service will beat it (see Known limitations).

The same figure descriptions also serve accessibility — figmark began as an
alt-text generator for formal Swedish ("myndighetssvenska") and can still emit
an annotated or tagged PDF alongside the Markdown.

## What the output looks like

A chart page in a Bank of Canada Monetary Policy Report comes out as (real,
unedited output):

```markdown
![Diagram, page 4](diagrams/page-004-diagram-01.png)

> **1. What the chart shows**
> The image contains two side-by-side line charts titled "Inflation has been
> slowing," showing the year-over-year percentage change of monthly inflation
> data.
> *   **X-axis:** Time, spanning from 2019 through the end of 2023.
> *   **Y-axis:** Percentage change (%). The left chart's scale ranges from
>     -2% to 12%.
>
> **2. Data series**
> *   **Canada:** Red line. **Canadian core CPI range:** a shaded red area.
> *   **United States:** Light blue line. **Euro area:** Green line. …
```

A text-only extractor drops that chart entirely; an OCR engine turns it into
axis-label noise. figmark hands your LLM the chart's actual content.

## What it does

- **Text + figures → Markdown.** Output is a single `<name>.md` with figures
  embedded as `![...](images/…)` followed by their description as a caption.
- **Vector diagram detection.** Matplotlib-style charts (which `get_images()`
  misses) are found by clustering vector drawings, rendered, and described with a
  diagram-specific prompt.
- **Scanned PDFs.** Falls back to OCR — Tesseract first, a vision model when
  Tesseract's quality is too low.
- **Configurable input formats.** PDF by default, plus the PyMuPDF-native
  formats (EPUB, XPS, FB2, CBZ, MOBI) via an `input.formats` allowlist in
  config — no extra dependency. **MS Office** (docx/xlsx/pptx) works too, via
  a sandboxed LibreOffice-headless conversion: use the **`-office` image
  variant** (`ghcr.io/ztein/figmark:<version>-office` — minimal headless
  LibreOffice, no Java/UI, same non-root/read-only posture and the same hard
  Trivy gate) or a local LibreOffice install, and enable the formats in
  `input.formats`. The default image stays slim — it does not carry
  LibreOffice's CVE surface. The gate sniffs the actual content (magic bytes +
  container inspection), so a mislabelled file fails loud instead of being
  mis-parsed.
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
pip install figmark
```

(or from source: `git clone` + `pip install -e .`)

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

### LibreChat / Mistral-OCR-compatible endpoint

The server also speaks the **Mistral OCR** wire format, so tools that expect that
API — [LibreChat](https://www.librechat.ai/docs/features/ocr) in particular — can
use figmark as a self-hosted, air-gappable OCR backend. Point the client's
`OCR_BASEURL` at `http(s)://<figmark-host>/v1` and set its `OCR_API_KEY` to the
figmark bearer token. figmark implements the four calls LibreChat's default
strategy makes: `POST /v1/files` → `GET /v1/files/{id}/url` → `POST /v1/ocr` →
`DELETE /v1/files/{id}`, returning `{ "pages": [ { "index", "markdown", "images" } ] }`
(`docs/tickets/T-052`).

**Supported `/v1/ocr` request parameters:** `model`, `document`
(`document_url` — a figmark signed file URL or an inline `data:` URL —
`image_url` with the same constraints, or `type: "file"` with a `file_id` from
`/v1/files`), `pages` (0-based indices and/or `"a-b"` ranges — unrequested
pages cost no pipeline work), `include_image_base64`, `image_limit`, and
`image_min_size`. `model` is echoed back but does not select a model — figmark
always runs its own pipeline. The response is contract-shaped
(`docs/tickets/T-058`): markdown figure refs are ids matching
`pages[].images[].id`, `images[]` carries bbox coordinates (PDF points; matching
the `dpi: 72` in `pages[].dimensions`) and a base64 data-URI when
`include_image_base64: true` — so figures can be re-inlined from the response
alone. Every other documented Mistral OCR parameter (the annotation formats,
`table_format`, …) is **rejected with a `422` naming the parameter** rather
than silently ignored, so a client never gets an answer with different
semantics than it asked for (`docs/tickets/T-057`).

Why figmark rather than the OCR service this contract comes from: figmark
fulfils the same API but aims to extract **more of the document's information
value** — for **born-digital, figure/diagram-heavy** documents it *describes*
figures and diagrams with a vision model instead of OCR'ing them into broken
text or dropping them — and keeps the data on your own network. **Limitation:** figmark's
raster OCR is Tesseract, not a vision-language model, so this backend is strongest
on born-digital / figure-heavy PDFs and **weaker than a VLM on messy scans and
handwriting**. It accepts the formats in the `input.formats` allowlist (PDF by
default; EPUB and the other PyMuPDF-native formats are free to enable); anything
else — including raster image input via `image_url` — returns `415`. Do not
deploy it expecting VLM-grade scan fidelity.

When a *scanned* page can't be OCR'd — the rendered page is too large for the
vision model even after figmark downscales it, or the model rejects/returns nothing
— the request fails **loud** with a `422` naming the page and the reason (and the
remedy: lower the OCR render DPI, or use a model with a larger image-input limit),
rather than a misleading generic backend error (`docs/tickets/T-053`).

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
