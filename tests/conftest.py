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
    monkeypatch.setenv("FIGMARK_API_KEY", "sk-test-fake-key")


@pytest.fixture
def mock_llm_server():
    """Run the OpenAI-compatible mock server in a background thread; yield its URL.

    Lets a real figmark OpenAI client make real HTTP calls with no internet.
    """
    import socket
    import threading
    import time

    import uvicorn

    from .mockllm.app import app as mock_app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = uvicorn.Server(
        uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("mock LLM server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


API_TEST_TOKEN = "secret-token"


@pytest.fixture
def make_api_app(env_with_key, project_root, tmp_path):
    """Factory: build a figmark API app with an injected (fake) client.

    Keeps the real config but skips network — the client is whatever the test
    passes (typically a FakeClient). Returns a callable so each test tunes the
    upload limit / concurrency / token.
    """

    def _make(
        client,
        *,
        max_upload_bytes: int = 50 * 1024 * 1024,
        max_concurrent_jobs: int = 2,
        token: str = API_TEST_TOKEN,
        request_timeout_seconds: float = 30.0,
        cache_admin_token: str | None = None,
    ):
        from figmark.api import ServerSettings, create_app
        from figmark.config import load_config

        cfg = load_config(project_root / "config.example.yaml")
        settings = ServerSettings(
            auth_token=token,
            config_path=project_root / "config.example.yaml",
            max_upload_bytes=max_upload_bytes,
            work_dir=tmp_path / "work",
            request_timeout_seconds=request_timeout_seconds,
            max_concurrent_jobs=max_concurrent_jobs,
            cache_admin_token=cache_admin_token,
        )
        return create_app(settings=settings, cfg=cfg, client=client)

    return _make
