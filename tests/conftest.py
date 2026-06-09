"""Shared pytest fixtures.

Sample PDFs are resolved from examples/ first (the curated, openly-licensed
corpus, e.g. fetched via examples/download_samples.py), then from a local
testfiler/ directory if present, and otherwise the test skips. This keeps CI
runnable from the committed/downloadable corpus while still letting a developer
run against their own local documents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = PROJECT_ROOT / "examples"
TESTFILES = PROJECT_ROOT / "testfiler"


def _resolve(*candidates: Path) -> Path | None:
    for c in candidates:
        if c.exists():
            return c
    return None


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def paper_pdf() -> Path:
    """A text-encoded article/paper with at least one embedded raster image."""
    p = _resolve(
        EXAMPLES / "paper.pdf",
        TESTFILES / "Pentland-and-Feldman-2008-Information-and-Organization.pdf",
    )
    if p is None:
        pytest.skip("No paper sample found (examples/paper.pdf). See examples/README.md.")
    return p


@pytest.fixture(scope="session")
def report_pdf() -> Path:
    """A report containing vector charts (for the diagram pipeline)."""
    p = _resolve(
        EXAMPLES / "report.pdf",
        TESTFILES / "penningpolitisk-rapport-mars-2026.pdf",
    )
    if p is None:
        pytest.skip("No report sample found (examples/report.pdf). See examples/README.md.")
    return p


@pytest.fixture(scope="session")
def guide_pdf() -> Path:
    """A document with a large cover image (for the OCR + resize paths)."""
    p = _resolve(
        EXAMPLES / "guide.pdf",
        TESTFILES / "Vagledning-om-etikprovning-EPM.pdf",
    )
    if p is None:
        pytest.skip("No guide sample found (examples/guide.pdf). See examples/README.md.")
    return p


@pytest.fixture(scope="session")
def scanned_pdf() -> Path:
    """An image-only scan (no text layer) that triggers the OCR pipeline."""
    p = _resolve(EXAMPLES / "scanned.pdf")
    if p is None:
        pytest.skip(
            "No scanned sample found (examples/scanned.pdf). "
            "Run: python examples/download_samples.py"
        )
    return p


@pytest.fixture(scope="session")
def long_pdf() -> Path:
    """A long (hundreds of pages) report, for pagination/scale checks."""
    p = _resolve(EXAMPLES / "long.pdf")
    if p is None:
        pytest.skip(
            "No long sample found (examples/long.pdf). "
            "Run: python examples/download_samples.py --include-large"
        )
    return p


@pytest.fixture
def env_with_key(monkeypatch):
    """For config tests that need a (fake) API key without hitting the real API."""
    monkeypatch.setenv("BERGET_API_KEY", "sk-test-fake-key")
