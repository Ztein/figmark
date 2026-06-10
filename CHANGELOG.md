# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

## [0.1.0] - 2026-06-08

First public release. Packaged the former internal `pdf_parser` tool as the
open-source `figmark`.

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
