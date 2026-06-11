"""Docker-gated runtime assertions for the figmark image.

Builds the image and checks the security/runtime properties that matter: non-root,
Tesseract with eng+swe, the package imports, and the server comes up healthy under
a read-only rootfs with auth enforced. Skipped automatically when Docker is absent
(so the normal offline suite is unaffected); run with `pytest -m docker`.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "figmark:pytest"


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return (
            subprocess.run(["docker", "version"], capture_output=True, timeout=15).returncode == 0
        )
    except Exception:
        return False


@pytest.fixture(scope="session")
def image() -> str:
    if not _docker_available():
        pytest.skip("Docker is not available")
    build = subprocess.run(
        ["docker", "build", "-q", "-t", IMAGE, str(ROOT)],
        capture_output=True,
        text=True,
    )
    if build.returncode != 0:
        pytest.fail(f"docker build failed:\n{build.stderr[-2000:]}")
    return IMAGE


def _run(image: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "run", "--rm", image, *args], capture_output=True, text=True)


def test_runs_as_non_root(image):
    assert _run(image, "id", "-u").stdout.strip() == "10001"


def test_tesseract_has_eng_and_swe(image):
    out = _run(image, "tesseract", "--list-langs")
    blob = out.stdout + out.stderr
    assert "eng" in blob and "swe" in blob


def test_python_imports(image):
    r = _run(image, "python", "-c", "import figmark, fastapi, fitz, pytesseract")
    assert r.returncode == 0, r.stderr


def test_server_healthy_under_readonly_rootfs(image):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    name = "figmark-pytest-run"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    up = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--security-opt",
            "no-new-privileges",
            "-e",
            "FIGMARK_AUTH_TOKEN=t",
            "-e",
            "FIGMARK_API_KEY=sk-test",
            "-p",
            f"{port}:8000",
            image,
        ],
        capture_output=True,
        text=True,
    )
    assert up.returncode == 0, up.stderr
    try:
        base = f"http://127.0.0.1:{port}"
        healthy = False
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"{base}/healthz", timeout=2) as resp:
                    if resp.status == 200:
                        healthy = True
                        break
            except Exception:
                time.sleep(0.5)
        assert healthy, "/healthz never returned 200"

        with urllib.request.urlopen(f"{base}/readyz", timeout=3) as resp:
            assert resp.status == 200

        # /v1/convert without auth must be rejected
        try:
            urllib.request.urlopen(
                urllib.request.Request(f"{base}/v1/convert", method="POST"), timeout=3
            )
            raise AssertionError("expected 401 without auth")
        except urllib.error.HTTPError as e:
            assert e.code == 401
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
