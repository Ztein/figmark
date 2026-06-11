# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Broken-text-layer warning (T-028).** A page whose extracted text is mostly
  mojibake (Private Use Area glyphs / replacement / control characters — a
  missing or broken font encoding) is now flagged with a loud warning suggesting
  a re-export or pre-OCR, instead of silently emitting garbage. A measurement on
  the eval corpus found this is rare for well-produced PDFs, so the decision was
  to warn + document the limitation rather than build auto-OCR detection (which
  risks false positives on number/symbol-heavy pages). Behaviour is unchanged —
  it only warns.
- **Selectable response format on `/v1/convert` (T-025).** A `format` field picks
  `json` (default) | `md` | `both`. `md` returns the raw Markdown body as
  `text/markdown` with the metadata echoed in `X-Figmark-*` response headers;
  `both` is an alias for `json` (which already carries markdown + metadata). An
  unknown value fails loudly with `422` — only the absent field defaults to
  `json`, for backward compatibility.
- **Token usage and optional cost per conversion (T-029).** Every conversion now
  reports `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`,
  `api_calls`, `calls_missing_usage`) on the API response and as a one-line CLI
  summary; the data was already returned by every completion and previously
  discarded. A monetary `estimated_cost` (+ `currency`) is added only when
  `api.input_token_price` and `api.output_token_price` are configured (per-token,
  provider-neutral — no hardcoded prices); otherwise it is `null`, never a
  misleading `0`. Cache hits make no call and cost nothing, as reflected.

### Changed

- **Per-page OCR decision (T-027).** The OCR/text choice is now made per page
  instead of once per document. A page is OCR'd only when it has little
  extractable text **and** a near-full-page image (`page_needs_ocr`), so a scanned
  page inside an otherwise text-encoded PDF is rescued (and announced with a loud
  banner) instead of being silently dropped — while genuinely sparse pages
  (dividers, figure-only) are not needlessly OCR'd. The document-wide `is_scanned`
  average is kept only as a logged hint.

### Removed

- **BREAKING (T-020): the deprecated `BERGET_API_KEY` / `BERGET_API_KEY_FILE`
  fallback is gone.** `FIGMARK_API_KEY` (or `FIGMARK_API_KEY_FILE`) is now the
  only accepted name. A key set under the old name is no longer honoured — the
  service fails loudly with "`FIGMARK_API_KEY` is not set" instead of silently
  falling back. This keeps the project's "fail loudly, no silent fallbacks"
  principle: rename the variable/secret to `FIGMARK_API_KEY`. The one-release
  deprecation window (v0.2.0) has elapsed.

## [0.2.0] - 2026-06-11

First public release.

### Added

- **Provider-neutral configuration (T-010).** `FIGMARK_API_KEY` (and
  `FIGMARK_API_KEY_FILE`) replace the provider-specific key name;
  `BERGET_API_KEY` still works as a deprecated fallback with a loud warning.
  The tracked config is now `config.example.yaml` with a placeholder endpoint —
  copy it to `config.yaml` and point it at any OpenAI-compatible vision endpoint
  (hosted or local). The compose secret is `figmark_api_key`.
- **GHCR images (T-017).** Every green build of `main` is published as
  `ghcr.io/ztein/figmark:edge`; releases publish `:<version>` and `:latest`.
  `compose.yaml` runs the GHCR image directly — no source checkout needed — and
  the air-gap tarball is saved under the GHCR name so `docker load` matches.
- **Zero-touch maintenance.** Dependabot (pip, docker, actions) with
  auto-approve/auto-merge for trusted authors (owner + bots) once all gates
  pass; outside contributors' PRs require maintainer review. Weekly scheduled
  security scans file an issue automatically on failure. CodeQL SAST, pip-audit
  as a blocking gate, all GitHub Actions SHA-pinned.
- **HTTP service + hardened container (air-gapped).** A FastAPI service
  (`figmark-server`, `POST /v1/convert` plus `healthz`/`readyz`/`version`) with
  bearer auth, input validation, a concurrency gate, and timeouts. The pipeline is
  refactored into `pipeline.convert`, shared by the CLI and the API (CLI behaviour
  unchanged). A multi-stage, non-root, digest-pinned, hash-locked image (Tesseract
  + eng/swe baked in) passes a hard Trivy gate, and a hardened `compose.yaml`
  deploys it with file-based secrets. An OpenAI-compatible mock server lets the
  whole stack run with no internet. New CI: hadolint, Trivy config/secret/image
  scans, SBOM, lockfile-freshness; release ships a scanned image tarball bundle.
  Docs: `SECURITY.md` and `docs/deployment.md`.
- **Output language follows the document (T-007).** A new `language.output`
  setting controls the language of image/diagram descriptions and the document
  summary. `auto` (default) detects the document's language once (cached to
  `output/<pdf>/document_language.txt`) and instructs the model explicitly;
  naming a language (`Swedish`, `English`, …) forces it. An English PDF now gets
  English captions instead of Swedish ones.

- **Document-type summary as context.** Before describing figures, figmark
  summarises the document once (what it is + what it's about) from its leading
  text and passes that summary into every image and diagram prompt, so figures
  are interpreted with the whole document in mind. Cached to
  `output/<pdf>/document_summary.txt`. Configurable via `document_summary.*`
  (`enabled`, `sample_words`, `prompt`).
- **Significance gate for images.** The vision model is asked to skip purely
  decorative images (logos, dividers, backgrounds, icons) by replying with a
  `[SKIP]` marker; such images are left out of the Markdown, annotations, and
  inlined text. No extra API calls — the decision is folded into the description
  call. Toggle with `significance.enabled`.

### Changed

- `config.yaml` gains three required sections — `significance`,
  `document_summary`, and `language` (following the existing "no hidden defaults"
  contract). Existing configs must add them — see `config.yaml` for the
  documented defaults.
- The default description/diagram/summary prompts no longer hardcode Swedish
  output; they describe the task and register, while `language.output` controls
  the language. Set `language.output: Swedish` for the previous behaviour.

## [0.1.0] - 2026-06-08 (internal milestone — never published)

Packaged the former internal `pdf_parser` tool as the open-source `figmark`.
This version was never tagged or published; the first public release will be
cut from `main` after the initial push, including everything under Unreleased.

### Added

- **Markdown output.** The primary output is now a single `<name>.md` where every
  image and vector diagram is embedded with `![...](path)` followed by its
  AI-generated description as a blockquote caption, in reading order.
- `figmark` console entry point (`pip install -e .` → `figmark <pdf>`).
- `pyproject.toml` packaging (PEP 621, hatchling), MIT license, CI, and a
  PyPI-ready release workflow via trusted publishing.
- Self-contained offline tests for payload preparation, diagram detection, and
  Markdown assembly so CI runs without an API key or external documents.

### Changed

- Project renamed to **figmark** and restructured to a `src/` layout
  (`src/figmark/`).
- All code, comments, logs, CLI help, and documentation translated to English.
  The description prompts in `config.yaml` remain in Swedish by design — formal
  Swedish ("myndighetssvenska") alt text is the product's domain output.
- Sample corpus decoupled: tests resolve documents from `examples/` (or a local
  `testfiler/`) and skip cleanly when absent.

### Notes

- The pipeline still targets any OpenAI-compatible vision endpoint; Berget.ai is
  the default, not a requirement.
- A configurable provider/model pipeline (per-task model selection) is planned
  for 0.2.
