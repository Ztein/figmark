from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from figmark.config import load_config


def _config_with_api(project_root: Path, tmp_path: Path, **api_overrides) -> Path:
    """Write a temp config = the example, with api.* keys overridden/added."""
    raw = yaml.safe_load((project_root / "config.example.yaml").read_text(encoding="utf-8"))
    raw["api"].update(api_overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_token_prices_are_optional_and_parsed(env_with_key, project_root: Path, tmp_path: Path):
    path = _config_with_api(
        project_root,
        tmp_path,
        input_token_price=2.5e-7,
        output_token_price=5e-7,
        currency="EUR",
    )
    cfg = load_config(path)
    assert cfg.api.input_token_price == 2.5e-7
    assert cfg.api.output_token_price == 5e-7
    assert cfg.api.currency == "EUR"


def test_token_prices_default_to_none(env_with_key, project_root: Path):
    cfg = load_config(project_root / "config.example.yaml")
    assert cfg.api.input_token_price is None
    assert cfg.api.output_token_price is None


def test_half_configured_prices_fail_loudly(env_with_key, project_root: Path, tmp_path: Path):
    path = _config_with_api(project_root, tmp_path, input_token_price=2.5e-7)
    with pytest.raises(RuntimeError, match="both be set"):
        load_config(path)


def test_non_numeric_price_fails_loudly(env_with_key, project_root: Path, tmp_path: Path):
    path = _config_with_api(
        project_root, tmp_path, input_token_price="cheap", output_token_price=5e-7
    )
    with pytest.raises(RuntimeError, match="must be a number"):
        load_config(path)


def test_load_default_config(env_with_key, project_root: Path):
    # The tracked example config ships a provider-neutral placeholder endpoint.
    cfg = load_config(project_root / "config.example.yaml")
    assert cfg.api.api_key == "sk-test-fake-key"
    assert cfg.api.base_url == "https://your-llm-endpoint.example/v1"
    assert cfg.api.model
    # The description prompt is intentionally kept written in Swedish (it describes
    # the task and the formal register), but it no longer pins the output language
    # — that is controlled by language.output (default "auto"). See T-007.
    assert cfg.description.prompt.startswith("Du ska ta emot bilder")
    assert "formellt" in cfg.description.prompt
    assert cfg.language.output == "auto"
    assert cfg.diagrams.enabled is True
    assert cfg.diagrams.prompt
    assert cfg.concurrency.max_workers >= 1
    assert cfg.ocr.language == "swe"
    assert cfg.significance.enabled is True
    assert cfg.document_summary.enabled is True
    assert cfg.document_summary.sample_words >= 1
    assert cfg.document_summary.prompt
    assert cfg.language.output


def test_load_config_requires_api_key(monkeypatch, project_root: Path):
    monkeypatch.delenv("FIGMARK_API_KEY", raising=False)
    monkeypatch.delenv("BERGET_API_KEY", raising=False)
    import figmark.config as config_module

    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="FIGMARK_API_KEY"):
        load_config(project_root / "config.example.yaml")


def test_legacy_berget_key_is_not_a_fallback(monkeypatch, project_root: Path):
    """A key set only under the old BERGET_API_KEY name must NOT be used.

    No silent fallback: with FIGMARK_API_KEY unset, the loader fails loudly even
    if BERGET_API_KEY is present, rather than quietly honouring the old name.
    """
    monkeypatch.delenv("FIGMARK_API_KEY", raising=False)
    monkeypatch.setenv("BERGET_API_KEY", "sk-legacy-key")
    import figmark.config as config_module

    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="FIGMARK_API_KEY"):
        load_config(project_root / "config.example.yaml")


def test_load_config_missing_file(env_with_key, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_missing_api_model_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  base_url: 'x'\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "tables:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="api.model is missing"):
        load_config(bad)


def test_missing_api_base_url_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "tables:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="api.base_url is missing"):
        load_config(bad)


def test_missing_concurrency_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "tables:\n  enabled: false\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="concurrency.max_workers is missing"):
        load_config(bad)


def test_missing_tables_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="tables.enabled is missing"):
        load_config(bad)


def test_missing_ocr_language_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "tables:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="ocr.language is missing"):
        load_config(bad)


def test_diagrams_enabled_requires_prompt(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: true\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="diagrams.prompt is missing"):
        load_config(bad)


def test_empty_yaml_fails_loudly(env_with_key, tmp_path: Path):
    """An empty config file should fail loudly on the first missing field."""
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="api.base_url is missing"):
        load_config(empty)


def test_whitespace_only_yaml_fails_loudly(env_with_key, tmp_path: Path):
    whitespace = tmp_path / "ws.yaml"
    whitespace.write_text("   \n\n  \n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="api.base_url is missing"):
        load_config(whitespace)


def test_empty_string_field_fails_loudly(env_with_key, tmp_path: Path):
    """An empty string counts as missing — otherwise we get cryptic errors later."""
    bad = tmp_path / "empty-model.yaml"
    bad.write_text(
        "api:\n  base_url: 'x'\n  model: ''\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "tables:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="api.model is missing"):
        load_config(bad)


def test_null_value_fails_loudly(env_with_key, tmp_path: Path):
    """null/None counts as missing too."""
    bad = tmp_path / "null.yaml"
    bad.write_text(
        "api:\n  base_url: 'x'\n  model: null\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "tables:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="api.model is missing"):
        load_config(bad)


def test_malformed_yaml_fails_with_clear_message(env_with_key, tmp_path: Path):
    """Broken YAML should give a clear error, not a cryptic internal exception."""
    bad = tmp_path / "broken.yaml"
    bad.write_text("api:\n  model: 'x\n  base_url: 'y'\n", encoding="utf-8")  # unclosed quote
    with pytest.raises((RuntimeError, Exception)) as exc_info:
        load_config(bad)
    # The error should name the file or what is broken.
    msg = str(exc_info.value).lower()
    assert "yaml" in msg or "config" in msg or str(bad) in str(exc_info.value), (
        f"The error message is not helpful enough:\n{exc_info.value}"
    )


def test_missing_context_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "tables:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="context"):
        load_config(bad)


def test_context_words_before_required(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'x'\n"
        "diagrams:\n  enabled: false\n"
        "tables:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n"
        "context:\n  enabled: true\n  words_after: 50\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="context.words_before is missing"):
        load_config(bad)


def test_diagrams_disabled_skips_prompt_requirement(env_with_key, tmp_path: Path):
    cfg_path = tmp_path / "no-diagrams.yaml"
    cfg_path.write_text(
        "api:\n  model: 'x'\n  base_url: 'x'\n"
        "input:\n  formats: ['pdf']\n"
        "cache:\n  enabled: false\n"
        "ocr:\n  language: 'swe'\n"
        "description:\n  prompt: 'describe'\n"
        "diagrams:\n  enabled: false\n"
        "tables:\n  enabled: false\n"
        "concurrency:\n  max_workers: 2\n"
        "context:\n  enabled: false\n  words_before: 0\n  words_after: 0\n"
        "significance:\n  enabled: false\n"
        "document_summary:\n  enabled: false\n"
        "language:\n  output: auto\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.diagrams.enabled is False
    assert cfg.diagrams.prompt == ""
    # A disabled document_summary does not require sample_words/prompt.
    assert cfg.document_summary.enabled is False
    assert cfg.significance.enabled is False


# A complete, valid config used by the required-field tests below. Each test
# omits exactly one field to assert it fails loudly.
_FULL_CONFIG = (
    "api:\n  model: 'x'\n  base_url: 'x'\n"
    "input:\n  formats: ['pdf']\n"
    "cache:\n  enabled: false\n"
    "ocr:\n  language: 'swe'\n"
    "description:\n  prompt: 'x'\n"
    "diagrams:\n  enabled: false\n"
    "tables:\n  enabled: false\n"
    "concurrency:\n  max_workers: 2\n"
    "context:\n  enabled: false\n  words_before: 0\n  words_after: 0\n"
    "significance:\n  enabled: true\n"
    "document_summary:\n  enabled: true\n  sample_words: 100\n  prompt: 'summarise'\n"
    "language:\n  output: auto\n"
)


def test_missing_significance_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(_FULL_CONFIG.replace("significance:\n  enabled: true\n", ""), encoding="utf-8")
    with pytest.raises(RuntimeError, match="significance.enabled is missing"):
        load_config(bad)


def test_missing_document_summary_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        _FULL_CONFIG.replace(
            "document_summary:\n  enabled: true\n  sample_words: 100\n  prompt: 'summarise'\n", ""
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="document_summary.enabled is missing"):
        load_config(bad)


def test_document_summary_enabled_requires_prompt(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        _FULL_CONFIG.replace(
            "document_summary:\n  enabled: true\n  sample_words: 100\n  prompt: 'summarise'\n",
            "document_summary:\n  enabled: true\n  sample_words: 100\n",
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="document_summary.prompt is missing"):
        load_config(bad)


def test_missing_language_fails_loudly(env_with_key, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(_FULL_CONFIG.replace("language:\n  output: auto\n", ""), encoding="utf-8")
    with pytest.raises(RuntimeError, match="language.output is missing"):
        load_config(bad)


def test_full_config_loads(env_with_key, tmp_path: Path):
    cfg_path = tmp_path / "full.yaml"
    cfg_path.write_text(_FULL_CONFIG, encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.significance.enabled is True
    assert cfg.document_summary.enabled is True
    assert cfg.document_summary.sample_words == 100
    assert cfg.document_summary.prompt == "summarise"
    assert cfg.language.output == "auto"
