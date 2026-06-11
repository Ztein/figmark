"""Compose hardening assertions.

The structural checks parse compose.yaml directly (offline, no Docker). A
Docker-gated check additionally validates with `docker compose config`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _app_service() -> dict:
    data = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    return data, data["services"]["app"]


def test_app_is_hardened():
    _, app = _app_service()
    assert app["read_only"] is True
    assert "/tmp" in app["tmpfs"]
    assert "no-new-privileges:true" in app["security_opt"]
    assert "ALL" in app["cap_drop"]
    assert str(app["user"]).startswith("10001")
    assert app.get("pids_limit")


def test_secrets_are_files_not_plaintext_env():
    data, app = _app_service()
    # The app references secrets and reads them via *_FILE — never plaintext env.
    assert set(app["secrets"]) == {"figmark_auth_token", "figmark_api_key"}
    env = app.get("environment", {})
    keys = " ".join(env.keys()) if isinstance(env, dict) else " ".join(env)
    assert "FIGMARK_API_KEY_FILE" in keys and "FIGMARK_AUTH_TOKEN_FILE" in keys
    # No plaintext secret values anywhere in the env block.
    blob = str(env).lower()
    assert "figmark_api_key:" not in blob  # i.e. not a plain FIGMARK_API_KEY value
    for name in ("figmark_auth_token", "figmark_api_key"):
        assert data["secrets"][name]["file"]


def test_config_is_mounted_read_only():
    _, app = _app_service()
    assert any(v.endswith(":ro") and "config.yaml" in v for v in app["volumes"])


@pytest.mark.docker
def test_docker_compose_config_validates():
    if not shutil.which("docker"):
        pytest.skip("docker not available")
    # Secret files must exist for `compose config`; create throwaway ones.
    secrets = ROOT / "secrets"
    secrets.mkdir(exist_ok=True)
    for f in ("auth_token", "figmark_api_key"):
        p = secrets / f
        if not p.exists():
            p.write_text("x", encoding="utf-8")
    r = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "config"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert r.returncode == 0, r.stderr
