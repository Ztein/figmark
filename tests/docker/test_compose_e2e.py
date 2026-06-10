"""Docker-gated, fully-offline end-to-end test of the compose stack.

Brings up the app + mock LLM with no internet, posts a PDF, and asserts the
returned Markdown — the air-gapped deployment proof. Run with `pytest -m docker`.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from ..fakes import synthetic_pdf

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "-f", str(ROOT / "compose.test.yaml")]


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "version"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


@pytest.fixture
def offline_stack(tmp_path):
    if not _docker_available():
        pytest.skip("Docker is not available")
    secrets = ROOT / "secrets"
    secrets.mkdir(exist_ok=True)
    (secrets / "auth_token").write_text("test-token", encoding="utf-8")
    (secrets / "berget_api_key").write_text("sk-test", encoding="utf-8")

    up = subprocess.run([*COMPOSE, "up", "--build", "-d"], capture_output=True, text=True, cwd=ROOT)
    if up.returncode != 0:
        subprocess.run([*COMPOSE, "down", "-v"], capture_output=True, cwd=ROOT)
        pytest.fail(f"compose up failed:\n{up.stderr[-2000:]}")
    try:
        yield
    finally:
        subprocess.run([*COMPOSE, "down", "-v"], capture_output=True, cwd=ROOT)


def test_offline_stack_converts_pdf(offline_stack, tmp_path):
    base = "http://127.0.0.1:8000"
    ready = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{base}/readyz", timeout=2) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(1)
    assert ready, "app /readyz never came up"

    synthetic_pdf(tmp_path / "doc.pdf")
    # multipart upload via curl (no extra deps); assert markdown comes back.
    out = subprocess.run(
        [
            "curl", "-s", "-X", "POST",
            "-H", "Authorization: Bearer test-token",
            "-F", f"file=@{tmp_path / 'doc.pdf'};type=application/pdf",
            f"{base}/v1/convert",
        ],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert "En bild på en katt." in out.stdout, out.stdout[:500]
