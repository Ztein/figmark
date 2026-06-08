# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
