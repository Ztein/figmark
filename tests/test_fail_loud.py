"""Fail-loudly fixes from the T-024 audit (no silent fallbacks)."""

from __future__ import annotations

import logging
from pathlib import Path

import fitz
import httpx
import pytest
from openai import APIError

from figmark.config import load_config
from figmark.images import extract_images_from_page
from figmark.pdf_loader import open_pdf
from figmark.pipeline import convert

from .fakes import FakeClient, synthetic_pdf

# --- F1: a failed image extraction is logged, not silently dropped --------


def test_failed_image_extraction_is_logged_not_silent(tmp_path: Path, capsys, monkeypatch):
    pdf = synthetic_pdf(tmp_path / "doc.pdf")  # has one embedded image
    doc = open_pdf(pdf)

    def boom(self, xref):
        raise RuntimeError("corrupt xref")

    monkeypatch.setattr(fitz.Document, "extract_image", boom)

    images = extract_images_from_page(doc, doc[0], 1, tmp_path / "out").images

    assert images == []  # the bad image is skipped …
    out = capsys.readouterr().out
    assert "WARNING" in out and "could not extract image" in out  # … but loudly


# --- F2: an API error during setup aborts, not swallowed ------------------


class _FailingClient(FakeClient):
    """Every completion call raises an API error (e.g. a bad key / 401)."""

    def _create(self, model, max_tokens, messages, **kwargs):
        raise APIError(
            "invalid api key",
            request=httpx.Request("POST", "http://test/v1/chat/completions"),
            body=None,
        )


def test_api_error_during_language_detection_aborts(
    env_with_key, project_root: Path, tmp_path: Path
):
    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    with pytest.raises(APIError):
        convert(pdf, cfg, tmp_path / "out", client=_FailingClient("desc"), quiet=True)


# --- T-032: loud warnings survive quiet mode via the structured logger -------


def test_loud_warning_survives_quiet_via_logger(
    env_with_key, project_root: Path, tmp_path: Path, monkeypatch, caplog
):
    """Under quiet=True (the server path), a loud pipeline warning must still reach
    the logger — it must not be silently dropped as it was when emit_loud was a
    no-op under quiet."""
    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    # Force the broken-text-layer loud event on the text-extracted page.
    monkeypatch.setattr("figmark.pipeline.text_garble_ratio", lambda _text: 0.9)

    with caplog.at_level(logging.WARNING, logger="figmark.pipeline"):
        convert(pdf, cfg, tmp_path / "out", client=FakeClient("a cat"), quiet=True)

    assert "text layer looks broken" in caplog.text
