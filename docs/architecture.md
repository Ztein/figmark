# Architecture

How figmark turns a PDF into Markdown where every figure is described. This is the
map of the pipeline and the modules behind it; for *why* a piece exists, the
[tickets](tickets/) carry the design notes.

## The pipeline at a glance

```
PDF
 │  open_pdf, is_scanned                                     (pdf_loader.py)
 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Per page                                                            │
│   text-encoded ──► iter_page_blocks  (text + image blocks)          │
│                    extract_images_from_page                         │  (images.py)
│                    find_diagram_regions + render   (vector charts)  │  (diagrams.py)
│   scanned ───────► ocr_page (Tesseract)                             │  (ocr.py)
│                    └─ low quality? ─► ocr_page_with_vision          │
└─────────────────────────────────────────────────────────────────────┘
 │
 ▼  detect_language (if language.output: auto)   ──► document_language.txt
 ▼  summarize_document                            ──► document_summary.txt   (summarize.py)
 │
 ▼  For each image / diagram, build a Job (skip if already cached)
 │     context  = N words before/after the figure                    (context.py)
 │     prompt   = document summary + context + language + skip gate   (describe.compose_prompt)
 ▼  run_jobs — ThreadPoolExecutor + live progress view               (parallel.py)
 │     describe_image / describe_diagram → cache one .txt per figure  (describe.py / diagrams.py)
 │
 ▼  assemble + to_markdown                                           (output.py)
 ▼
output/<name>/<name>.md   (+ raw_text.txt, optional <name>_alt_text.pdf)
```

The orchestration lives in [`main.run`](../src/figmark/main.py).

## Stages

### 1. Classify: text-encoded or scanned — per page (T-027)

The OCR/text choice is made **per page**, not once per document.
[`page_needs_ocr`](../src/figmark/pdf_loader.py) sends a page down the OCR path only
when it has little extractable text (< `PAGE_OCR_MIN_CHARS`, 50) **and** a
near-full-page image covers it (`page_image_coverage` ≥ `PAGE_OCR_IMAGE_COVERAGE`,
0.5) — i.e. the text really is locked inside a raster. A page with little text but
no large image (a section divider, a figure-only page) is sparse-but-digital and
stays on the text path, so it is not needlessly OCR'd. This means a scanned page
inside an otherwise text-encoded PDF is handled instead of silently dropped; such
an OCR "rescue" is announced with a loud `!!!` banner.
[`is_scanned`](../src/figmark/pdf_loader.py) (the document-wide average) is kept
only as a logged hint.

### 2a. Text extraction (text-encoded PDFs)

[`iter_page_blocks`](../src/figmark/pdf_loader.py) returns the page as ordered
blocks — `TextBlock`s and `ImageBlock`s sorted in reading order (by `y`, then `x`).
[`extract_images_from_page`](../src/figmark/images.py) saves the embedded raster
images, skipping sub-50px decorative icons.
[`find_diagram_regions`](../src/figmark/diagrams.py) finds vector charts that
`get_images()` never sees (matplotlib-style PDFs) by clustering drawing operations,
splitting stacked charts on internal gaps, and expanding the box to capture axis
titles and source lines; each region is rendered to PNG.

### 2b. OCR (scanned PDFs)

[`ocr_page`](../src/figmark/ocr.py) runs Tesseract (local, free). If the result is
too short or low-confidence (`should_fallback`), the page is sent to the vision
model for transcription (`ocr_page_with_vision`). The fallback is shouted loudly.

### 3. Document language and summary

If `language.output` is `auto`, [`detect_language`](../src/figmark/summarize.py)
makes one cheap call to name the document's language (cached to
`document_language.txt`). A soft "answer in the document's language" hint is
unreliable against the Swedish-written prompts, so the detected name is later
injected into every prompt explicitly. See [T-007](tickets/T-007-description-language-follows-document.md).

[`summarize_document`](../src/figmark/summarize.py) then summarises the document
once from its leading text (cached to `document_summary.txt`) so every figure is
interpreted with the whole document in mind. See [T-006](tickets/T-006-text-context-around-images.md).

### 4. Describe figures (parallel, cached)

Each image and diagram becomes a `Job`. Anything already on disk
(`descriptions/<fig>.txt`) is a cache hit and never scheduled.
[`run_jobs`](../src/figmark/parallel.py) runs the rest through a
`ThreadPoolExecutor` (`concurrency.max_workers`) with a `rich` live view. The
prompt sent for each figure is built by
[`compose_prompt`](../src/figmark/describe.py):

```
[Document type]   ← the document summary
[Text context before/after the image]   ← context.py, words_before / words_after
[Task]
  <description.prompt or diagrams.prompt>
  + significance skip instruction (images only)
  + "Write your answer in <language>."
```

**Significance gate.** When `significance.enabled`, the model is told to answer
with `[SKIP]` for purely decorative images (logos, dividers, icons). It costs no
extra call — the decision rides on the describe call that would happen anyway — and
skipped figures are left out of every output.

### 5. Assemble the output

[`to_markdown`](../src/figmark/output.py) interleaves text and figures in reading
order: each described figure is embedded with `![...](path)` followed by its
description as a blockquote caption. `assemble` also writes a plain `raw_text.txt`.
With `--annotate-pdf`, [`annotate_pdf`](../src/figmark/annotate.py) writes the
descriptions back into a copy of the PDF as text annotations. See
[T-005](tickets/T-005-pdf-annotations.md).

## Module map

| Module | Responsibility |
|--------|----------------|
| `main.py` | CLI + pipeline orchestration (`run`) |
| `config.py` | Load/validate `config.yaml` into typed dataclasses (no hidden defaults) |
| `pdf_loader.py` | Open PDF, page → ordered blocks, scanned classification |
| `images.py` | Extract embedded raster images, filter decoratives |
| `diagrams.py` | Detect/render vector charts; describe them |
| `ocr.py` | Tesseract OCR with vision-model fallback |
| `context.py` | N words of text before/after a figure |
| `summarize.py` | Document-language detection + document summary |
| `describe.py` | Prompt composition, image description, language/skip helpers |
| `parallel.py` | ThreadPoolExecutor runner + live progress view |
| `output.py` | Assemble Markdown and raw text |
| `annotate.py` | Write descriptions back into the PDF as annotations |

## Outputs

Everything for a run lands in `output/<pdf-name>/`:

| Path | What it is |
|------|------------|
| `<name>.md` | **Primary output** — text with figures + descriptions inline |
| `raw_text.txt` | Text only, no descriptions |
| `images/`, `diagrams/` | Extracted figures |
| `descriptions/`, `diagram_descriptions/` | One `.txt` per figure — **the cache** |
| `document_summary.txt`, `document_language.txt` | Cached document-level context |
| `<name>_alt_text.pdf` | Optional annotated PDF (`--annotate-pdf`) |

Re-running reuses the caches and makes no API calls. To regenerate from scratch,
delete the relevant directory (changing `language.output` or `context.*` requires
clearing `descriptions/`, since descriptions are cached per figure).

## Configuration vs. constants

Two tiers, by design:

- **User knobs** live in `config.yaml` (start from [`config.example.yaml`](../config.example.yaml)) and are loaded as required
  fields by `config.py`: `api`, `ocr.language`, `language.output`,
  `description.prompt`, `diagrams.*`, `concurrency.max_workers`, `context.*`,
  `significance.enabled`, `document_summary.*`.
- **Technical constants** (clustering thresholds, OCR thresholds, image-size
  filters, render DPI, retry counts, payload caps) live as documented module-level
  constants in the module that uses them — tune them there.

## Service & deployment

The same pipeline runs two ways, sharing one code path
([`pipeline.convert`](../src/figmark/pipeline.py)):

- **CLI** — [`main.run`](../src/figmark/main.py) loads config, builds the client,
  calls `convert`, prints a summary.
- **HTTP service** — [`api.py`](../src/figmark/api.py) (`figmark-server`) exposes
  `POST /v1/convert` plus `healthz`/`readyz`/`version`. It injects its own client
  into `convert`, runs it in a worker thread (quiet, no TTY), and adds the
  service concerns: bearer auth, input validation, a concurrency gate, and
  timeouts. Ops/secret knobs come from the environment (`ServerSettings`), so the
  strict `config.yaml` contract is untouched.

For tests and air-gapped runs, [`tests/mockllm/`](../tests/mockllm/) is a tiny
OpenAI-compatible server that stands in for the vision model, so the whole stack
runs with no internet. The service is packaged as a hardened, self-contained
image ([Dockerfile](../Dockerfile)) and deployed with
[`compose.yaml`](../compose.yaml); see [deployment.md](deployment.md) and
[SECURITY.md](../SECURITY.md).

## Design principles

- **Fail loudly.** No silent fallbacks; strategy switches are shouted with `!!!`
  banners (see `main.loud`). The document summary is the one deliberate exception —
  it is best-effort context, so a failed summary only warns and continues.
- **Deterministic output.** Descriptions are assembled after all calls finish, so
  the Markdown is identical regardless of worker count or completion order.
- **Cache everything expensive.** Every API result is one file on disk.
