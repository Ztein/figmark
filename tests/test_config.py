from __future__ import annotations

from pathlib import Path

import pytest

from src.config import load_config


def test_load_default_config(env_with_key, project_root: Path):
    cfg = load_config(project_root / "config.yaml")
    assert cfg.api.api_key == "sk-test-fake-key"
    assert cfg.api.base_url == "https://api.berget.ai/v1"
    assert cfg.api.model
    assert cfg.description.prompt.startswith("Du ska ta emot bilder")
    assert "myndighetssvenska" in cfg.description.prompt
    assert cfg.diagrams.enabled is True
    assert cfg.diagrams.prompt
    assert cfg.concurrency.max_workers >= 1
    assert cfg.ocr.language == "swe"


def test_load_config_requires_api_key(monkeypatch, project_root: Path):
    monkeypatch.delenv("BERGET_API_KEY", raising=False)
    import src.config as config_module
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="BERGET_API_KEY"):
        load_config(project_root / "config.yaml")


def test_load_config_missing_file(env_with_key, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_missing_api_model_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  base_url: 'x'\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="api.model saknas"):
        load_config(bad)


def test_missing_api_base_url_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="api.base_url saknas"):
        load_config(bad)


def test_missing_concurrency_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="concurrency.max_workers saknas"):
        load_config(bad)


def test_missing_ocr_language_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="ocr.language saknas"):
        load_config(bad)


def test_diagrams_enabled_requires_prompt(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: true\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="diagrams.prompt saknas"):
        load_config(bad)


def test_empty_yaml_fails_loudly(env_with_key, tmp_path: Path):
    """En tom config-fil ska smälla med tydligt meddelande på första saknade fält."""
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="api.base_url saknas"):
        load_config(empty)


def test_whitespace_only_yaml_fails_loudly(env_with_key, tmp_path: Path):
    whitespace = tmp_path / "ws.yaml"
    whitespace.write_text("   \n\n  \n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="api.base_url saknas"):
        load_config(whitespace)


def test_empty_string_field_fails_loudly(env_with_key, tmp_path: Path):
    """Tom sträng räknas som saknat — annars får vi obegripliga fel längre ner."""
    bad = tmp_path / "empty-model.yaml"
    bad.write_text(
        "api:\n  base_url: 'x'\n  model: ''\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="api.model saknas"):
        load_config(bad)


def test_null_value_fails_loudly(env_with_key, tmp_path: Path):
    """null/None räknas också som saknat."""
    bad = tmp_path / "null.yaml"
    bad.write_text(
        "api:\n  base_url: 'x'\n  model: null\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="api.model saknas"):
        load_config(bad)


def test_malformed_yaml_fails_with_clear_message(env_with_key, tmp_path: Path):
    """Trasig YAML ska ge ett tydligt fel, inte ett kryptiskt internt undantag."""
    bad = tmp_path / "broken.yaml"
    bad.write_text("api:\n  model: 'x\n  base_url: 'y'\n", encoding="utf-8")  # ostängd citat
    with pytest.raises((RuntimeError, Exception)) as exc_info:
        load_config(bad)
    # Felet ska nämna vilken fil eller vad som är trasigt
    msg = str(exc_info.value).lower()
    assert "yaml" in msg or "config" in msg or str(bad) in str(exc_info.value), (
        f"Felmeddelandet ger inte tillräcklig hjälp:\n{exc_info.value}"
    )


def test_missing_context_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="context"):
        load_config(bad)


def test_context_words_before_required(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n"
        "context:\n  enabled: true\n  words_after: 50\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="context.words_before saknas"):
        load_config(bad)


def test_diagrams_disabled_skips_prompt_requirement(env_with_key, tmp_path: Path):
    cfg_path = tmp_path / "no-diagrams.yaml"
    cfg_path.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'beskriv'\n"
        "diagrams:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n"
        "context:\n  enabled: false\n  words_before: 0\n  words_after: 0\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.diagrams.enabled is False
    assert cfg.diagrams.prompt == ""
