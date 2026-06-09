# Contributing to figmark

Thanks for your interest in improving figmark! This document covers how to set
up a development environment, run the tests, and submit changes.

## Development setup

```bash
git clone https://github.com/joelstenberg/figmark
cd figmark
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

System dependency for the OCR path (scanned PDFs):

```bash
# macOS
brew install tesseract tesseract-lang
# Debian/Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-swe
```

Copy `.env.example` to `.env` and add your Berget API key if you want to run the
live tests:

```bash
cp .env.example .env
# edit .env and set BERGET_API_KEY
```

## Running the tests

```bash
# Fast: everything except the live API tests (no key, no cost)
pytest -m "not live"

# Live tests only (calls the real API — costs money, takes minutes)
pytest -m "live"

# Everything
pytest
```

The offline suite runs against a small sample corpus. See
[examples/README.md](examples/README.md) for how to fetch sample documents;
tests that need a sample skip cleanly when it is absent.

## Linting and formatting

We use [ruff](https://docs.astral.sh/ruff/) for both linting and formatting.
CI checks both, so run them before pushing:

```bash
ruff check src tests
ruff format --check src tests
# auto-fix:
ruff check --fix src tests && ruff format src tests
```

## Pull requests

- Branch off `main` and open a PR against `main`.
- Keep changes focused; one logical change per PR.
- Add or update tests for behaviour changes.
- Make sure `ruff check`, `ruff format --check`, and `pytest -m "not live"` pass.
- Follow the project's "fail loudly" principle: no silent fallbacks — when the
  pipeline changes strategy, it should say so clearly.

## Understanding the codebase

[docs/architecture.md](docs/architecture.md) walks through the pipeline end to end
— the stages, the module map, the outputs, and how `config.yaml` maps to
behaviour. The [docs/tickets/](docs/tickets/) carry the design notes for why each
piece exists.

## Design principles

- **Fail loudly.** No silent fallbacks. Strategy switches (e.g. Tesseract →
  vision-OCR) are shouted with clear `!!!` banners.
- **Run for real.** Tests run against the real API by default; mocking is used
  only for isolated unit tests of internal logic.
- **User knobs in `config.yaml`, technical knobs in code.** Thresholds and tuning
  constants live as module-level constants in `src/figmark/<module>.py`.
