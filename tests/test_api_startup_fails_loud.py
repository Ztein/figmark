"""Phase 2: the server fails loudly at startup on missing secrets / bad config."""

from __future__ import annotations

import pytest


def test_settings_from_env_requires_auth_token(monkeypatch):
    monkeypatch.delenv("FIGMARK_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("FIGMARK_AUTH_TOKEN_FILE", raising=False)
    from figmark.api import ServerSettings

    with pytest.raises(RuntimeError, match="FIGMARK_AUTH_TOKEN"):
        ServerSettings.from_env()


def test_settings_reads_token_from_file(monkeypatch, tmp_path):
    monkeypatch.delenv("FIGMARK_AUTH_TOKEN", raising=False)
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("FIGMARK_AUTH_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("BERGET_API_KEY", "sk-test-fake-key")
    from figmark.api import ServerSettings

    settings = ServerSettings.from_env()
    assert settings.auth_token == "file-token"


def test_create_app_fails_on_bad_config(env_with_key, tmp_path):
    from figmark.api import ServerSettings, create_app

    settings = ServerSettings(
        auth_token="t",
        config_path=tmp_path / "missing.yaml",
        max_upload_bytes=1024,
        work_dir=tmp_path / "work",
        request_timeout_seconds=5,
        max_concurrent_jobs=1,
    )
    with pytest.raises((FileNotFoundError, RuntimeError)):
        create_app(settings=settings, client=object())


def test_berget_key_file_is_surfaced_for_config(monkeypatch, tmp_path):
    monkeypatch.setenv("FIGMARK_AUTH_TOKEN", "t")
    monkeypatch.delenv("BERGET_API_KEY", raising=False)
    key_file = tmp_path / "key"
    key_file.write_text("sk-from-file\n", encoding="utf-8")
    monkeypatch.setenv("BERGET_API_KEY_FILE", str(key_file))
    from figmark.api import ServerSettings

    ServerSettings.from_env()
    import os

    assert os.environ["BERGET_API_KEY"] == "sk-from-file"
