# Architecture

How figmark turns a PDF into a faithful Markdown representation — text with
structure, tables, and every figure described. This is the map of the pipeline and
the modules behind it; for *why* a piece exists, the [tickets](tickets/) carry the
design notes. **New here? Read [Where things stand](#where-things-stand) at the
bottom first** — it summarises the current capabilities, the open Phase-2 items,
and the bench-before-code discipline.

## The pipeline at a glance

```
PDF
 │  open_pdf, is_scanned                                     (pdf_loader.py)
 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Per page                                                            │
│   text-encoded ──► iter_page_blocks  (text/image blocks; font size, │
│                      bold; hyperlinks wrapped; column-aware order)   │  (pdf_loader.py)
│                    extract_images_from_page                         │  (images.py)
│                    find_diagram_regions + render   (vector charts)  │  (diagrams.py)
│                    find_table_blocks               (ruled tables)   │  (tables.py)
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
 ▼  strip_boilerplate  (running headers/footers, page numbers)        (boilerplate.py)
 ▼  to_markdown  (headings/lists inferred, tables, figures, links)    (output.py + structure.py)
 ▼  build_figure_manifest                          ──► <name>.figures.json
 ▼
output/<name>/<name>.md   (+ raw_text.txt, figures.json,
                            optional <name>_alt_text.pdf / <name>_tagged.pdf)
```

The orchestration lives in [`pipeline.convert`](../src/figmark/pipeline.py), called
by both [`main.run`](../src/figmark/main.py) (CLI) and [`api.py`](../src/figmark/api.py)
(HTTP service).

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
blocks — `TextBlock`s, `ImageBlock`s, `DiagramBlock`s, `TableBlock`s. Each
`TextBlock` carries the dominant span's **font size and bold flag** (for heading
inference, T-042) and has its **hyperlinks wrapped** as Markdown `[anchor](url)`
(T-044). Ordering is **column-aware**: `sort_blocks_reading_order` detects column
boundaries from clustered left-edges so a two-column page is not interleaved
(T-036); a single-column page keeps the plain `(y, x)` flow.

[`extract_images_from_page`](../src/figmark/images.py) saves embedded raster images
(skipping sub-50px icons) and returns an `ImageExtraction` that also reports how
many were filtered (T-002).
[`find_diagram_regions`](../src/figmark/diagrams.py) finds vector charts that
`get_images()` never sees (matplotlib-style PDFs) by clustering drawing operations
(near-linear x-sweep, T-037), splitting stacked charts on internal gaps, and
expanding the box to capture axis titles and source lines; each region is rendered
to PNG. Internal label text inside a diagram region is suppressed from the body
(T-008).
[`find_table_blocks`](../src/figmark/tables.py) detects ruled data tables with
PyMuPDF `find_tables()` behind a conservative 3-gate filter (drop diagram overlaps,
require a numeric body, reject axis-ladders) — validated to 100 % detection /
99 % cell-recall on a labelled bench (T-030/T-031). Text consumed by a kept table
is removed from the loose flow.

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

### 4b. Strip boilerplate (before assembly)

[`strip_boilerplate`](../src/figmark/boilerplate.py) drops running headers/footers
and page numbers so they do not leak into the text as repeated noise. A margin
`TextBlock` is removed only when its text recurs on ≥ half the pages **or** it is
page-number-shaped — margin position *and* repetition/shape, so real content is
safe. No-op under 4 pages. See [T-043](tickets/T-043-strip-running-headers-footers.md).

### 5. Assemble the output

[`to_markdown`](../src/figmark/output.py) interleaves text, tables and figures in
reading order:

- **Structure** ([`structure.py`](../src/figmark/structure.py), T-042): the body
  font size is the most common one; short, horizontal blocks that are larger or
  bold become Markdown headings (`#`/`##`/`###`) ranked by size, and bullet lines
  become list items. Rotated margin text (e.g. an arXiv stamp) is rejected by a
  horizontal gate. 100 % heading precision/recall on the bench.
- **Tables** are rendered as GitHub Markdown tables; **figures** are embedded with
  `![...](path)` + the description as a blockquote caption; **hyperlinks** already
  live in the block text as `[anchor](url)`.

`assemble` also writes a plain `raw_text.txt`.
[`build_figure_manifest`](../src/figmark/output.py) writes `<name>.figures.json`, a
machine-readable index of every figure (`id, page, kind, bbox, path, description,
skipped`) for follow-up questions about a specific figure (T-041).

Two optional accessibility artifacts are produced on demand:

- `--annotate-pdf` → [`annotate_pdf`](../src/figmark/annotate.py) writes the
  descriptions back as PDF text annotations (`<name>_alt_text.pdf`,
  [T-005](tickets/T-005-pdf-annotations.md)).
- `--tagged-pdf` → [`tag_pdf`](../src/figmark/tagged.py) writes a structure-tree
  copy (`<name>_tagged.pdf`) with a `/Figure` element per figure carrying `/Alt`,
  plus `/MarkInfo` and `/Lang` — the PDF/UA foundation (T-004, Phase 1).

## Module map

| Module | Responsibility |
|--------|----------------|
| `main.py` | CLI entry point (`run`); flags `--annotate-pdf`, `--tagged-pdf` |
| `pipeline.py` | The shared `convert` orchestration (CLI + API call into it) |
| `config.py` | Load/validate `config.yaml` into typed dataclasses (no hidden defaults) |
| `pdf_loader.py` | Open PDF; page → ordered blocks (font size/bold, hyperlinks, column-aware order); scanned classification |
| `images.py` | Extract embedded raster images; report filtered count |
| `diagrams.py` | Detect/render vector charts; describe them; significance gate |
| `tables.py` | Detect ruled data tables behind the 3-gate filter → `TableBlock` |
| `structure.py` | Infer headings/lists from typography (T-042) |
| `boilerplate.py` | Strip running headers/footers + page numbers (T-043) |
| `ocr.py` | Tesseract OCR with vision-model fallback |
| `context.py` | N words of text before/after a figure |
| `summarize.py` | Document-language detection + document summary |
| `describe.py` | Prompt composition, image description, language/skip + cache-key helpers |
| `parallel.py` | ThreadPoolExecutor runner + live progress view |
| `output.py` | Assemble Markdown + raw text; figure manifest |
| `annotate.py` | Write descriptions back into the PDF as text annotations |
| `tagged.py` | Write a PDF/UA structure-tree copy (pikepdf) |
| `usage.py` | Token-usage tracking + optional cost estimate |
| `api.py` | FastAPI service (`/v1/convert`); auth, validation, concurrency, timeouts |

## Outputs

Everything for a run lands in `output/<pdf-name>/`:

| Path | What it is |
|------|------------|
| `<name>.md` | **Primary output** — structured text (headings/lists), tables, figures + descriptions, hyperlinks |
| `raw_text.txt` | Text only, no figure descriptions |
| `<name>.figures.json` | Machine-readable figure index (T-041) |
| `images/`, `diagrams/` | Extracted figures |
| `descriptions/`, `diagram_descriptions/` | One `.txt` per figure — **the cache** |
| `document_summary.txt`, `document_language.txt` | Cached document-level context |
| `<name>_alt_text.pdf` | Optional annotated PDF (`--annotate-pdf`) |
| `<name>_tagged.pdf` | Optional PDF/UA structure-tree copy (`--tagged-pdf`) |

Re-running reuses the caches and makes no API calls. The figure cache key now
includes a fingerprint of the config that produced it (model, prompt, resolved
language, significance, context, summary settings), so **changing any of those
automatically misses the cache and regenerates** — no manual directory deletion
needed (T-034).

## Configuration vs. constants

Two tiers, by design:

- **User knobs** live in `config.yaml` (start from [`config.example.yaml`](../config.example.yaml)) and are loaded as required
  fields by `config.py`: `api`, `ocr.language`, `language.output`,
  `description.prompt`, `diagrams.*`, `tables.enabled`, `concurrency.max_workers`,
  `context.*`, `significance.enabled`, `document_summary.*`. **Adding a required
  field is a breaking change** — update `config.example.yaml`, `config.yaml`, and
  `compose/config.test.yaml` together, or the container's startup and the
  `test_config.py` fixtures fail loudly (the docker-gated e2e will catch it).
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
- **Bench before code.** Any detection/extraction change is justified by a small
  labelled bench with the threshold written down and the numbers in the PR — never
  by intuition. This has repeatedly caught false alarms before code shipped (e.g.
  T-040 was withdrawn when the bench showed the "missed" figures were raster).

## Benches

Reproducible, committed harnesses under [`scripts/`](../scripts/) (PDFs are
gitignored; benches skip when absent). They make **no API calls** — pure
detection/extraction — so they run offline.

| Bench | What it measures | Ground truth |
|---|---|---|
| `table_bench/bench.py` | Table detection + cell-recall vs pdfplumber (T-030) | hand-transcribed grids |
| `recall_bench/bench.py` | Figure recall — vector (detector) + raster (image path) (T-035); `download.py` fetches genre 2 | per-page figure counts |
| `structure_bench/bench.py` | Heading detection precision/recall (T-042) | hand-labelled headings |
| `probe_tables.py` | One-off sweep that located the table corpus | — |

## Where things stand

The Markdown representation is now **structured**: headings/lists, ruled tables,
column-aware reading order, boilerplate stripped, hyperlinks preserved, figures
described + indexed in `figures.json`. The [tickets index](tickets/README.md) is the
live status board (one row per ticket). As of 2026-06-24, two items are
deliberately **Phase 1 / open**, each blocked on something external — start here if
picking up:

- **[T-044](tickets/T-044-hyperlinks-and-footnotes.md) — footnotes (Phase 2).**
  Hyperlinks are done; footnote segregation is deferred because a prototype showed
  body text (~9.9pt) is indistinguishable from a real footnote (8.9pt) by size
  alone, so a naive rule eats body text. Needs a tighter size threshold +
  footnote-marker detection + a precision bench.
- **[T-004](tickets/T-004-tagged-pdf-pdfua.md) — PDF/UA conformance (Phase 2).**
  The structure-tree foundation ships; full conformance needs MCID-anchored marked
  content + full-content tagging, and **validation with veraPDF/PAC + a screen
  reader** (which couldn't run in the dev environment).

**The highest-leverage next step** is the *document model* sketched in
[T-042](tickets/T-042-document-structure-headings-lists.md) Option 2: a typed
block model (`heading`/`paragraph`/`list`/`table`/`figure`) that PDF maps *into* and
Markdown renders *out of*. It is the shared abstraction that carries the structure
work over to the planned Word/Excel/PowerPoint inputs — so they don't each
re-derive structure.
