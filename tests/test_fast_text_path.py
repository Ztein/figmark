"""T-051: a figure-less text PDF must not spend baseline API calls.

The document summary and the auto language detection exist only to contextualise
figure descriptions. When detection finds zero images and zero diagram regions,
neither call should be made — and the skip must be logged, not silent (T-024).
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz

from figmark.config import load_config
from figmark.pipeline import convert

from .fakes import DETECTED_LANGUAGE, FakeClient


def text_only_pdf(path: Path) -> Path:
    """Write a one-page PDF containing only text — no images, no drawings."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Plain prose about monetary policy. " * 20)
    page.insert_text((72, 300), "More plain prose, still no figures. " * 20)
    doc.save(path)
    doc.close()
    return path


def test_text_only_pdf_makes_no_api_calls(env_with_key, project_root: Path, tmp_path: Path):
    pdf = text_only_pdf(tmp_path / "textonly.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    client = FakeClient("should never be called")

    result = convert(pdf, cfg, tmp_path / "output", client=client, quiet=True)

    assert client.language_prompts == [], "language detection must be skipped with no figures"
    assert client.summary_prompts == [], "document summary must be skipped with no figures"
    assert client.describe_prompts == []
    assert result.figure_count == 0
    assert result.usage.api_calls == 0
    # The text itself still comes through untouched.
    assert "Plain prose about monetary policy." in result.markdown
    # No detection ran, so the configured value is passed through as-is.
    assert result.language == cfg.language.output


def test_text_only_skip_is_logged_not_silent(
    env_with_key, project_root: Path, tmp_path: Path, caplog
):
    pdf = text_only_pdf(tmp_path / "textonly.pdf")
    cfg = load_config(project_root / "config.example.yaml")

    with caplog.at_level(logging.INFO, logger="figmark.pipeline"):
        convert(pdf, cfg, tmp_path / "output", client=FakeClient("unused"), quiet=True)

    assert any(
        "no figures" in rec.message.lower() and "skip" in rec.message.lower()
        for rec in caplog.records
    ), "skipping the summary/language calls must be logged (T-024: no silent behaviour change)"


def test_tagged_output_still_detects_language_without_figures(
    env_with_key, project_root: Path, tmp_path: Path
):
    """--tagged sets the document /Lang, so auto-detection must still run for it."""
    pdf = text_only_pdf(tmp_path / "textonly.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    client = FakeClient("unused")

    result = convert(pdf, cfg, tmp_path / "output", client=client, tagged=True, quiet=True)

    assert len(client.language_prompts) == 1
    assert result.language == DETECTED_LANGUAGE
    assert client.summary_prompts == [], "the summary is figure context only — still skipped"


def test_document_with_figure_keeps_baseline_calls(
    env_with_key, project_root: Path, tmp_path: Path
):
    """Guard against over-skipping: one figure → summary + language run as before."""
    from .fakes import synthetic_pdf

    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    client = FakeClient("En bild på en katt.")

    convert(pdf, cfg, tmp_path / "output", client=client, quiet=True)

    assert len(client.language_prompts) == 1
    assert len(client.summary_prompts) == 1
    assert len(client.describe_prompts) == 1
