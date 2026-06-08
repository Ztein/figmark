from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTFILES = PROJECT_ROOT / "testfiler"


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def pentland_pdf() -> Path:
    p = TESTFILES / "Pentland-and-Feldman-2008-Information-and-Organization.pdf"
    if not p.exists():
        pytest.skip(f"Saknar test-PDF: {p}")
    return p


@pytest.fixture(scope="session")
def etikprovning_pdf() -> Path:
    p = TESTFILES / "Vagledning-om-etikprovning-EPM.pdf"
    if not p.exists():
        pytest.skip(f"Saknar test-PDF: {p}")
    return p


@pytest.fixture(scope="session")
def penningpolitisk_pdf() -> Path:
    p = TESTFILES / "penningpolitisk-rapport-mars-2026.pdf"
    if not p.exists():
        pytest.skip(f"Saknar test-PDF: {p}")
    return p


@pytest.fixture
def env_with_key(monkeypatch):
    """För config-tester som behöver en (fake) API-nyckel utan att slå mot Berget."""
    monkeypatch.setenv("BERGET_API_KEY", "sk-test-fake-key")
