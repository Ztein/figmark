"""Broken-text-layer detection + loud warning (T-028)."""

from __future__ import annotations

from pathlib import Path

from figmark import pipeline as pipeline_module
from figmark.config import load_config
from figmark.pdf_loader import text_garble_ratio

from .fakes import FakeClient, synthetic_pdf

# --- unit: text_garble_ratio ---------------------------------------------


def test_clean_text_scores_zero():
    assert text_garble_ratio("Helt vanlig svensk text med siffror 123 och tecken.") == 0.0
    assert text_garble_ratio("") == 0.0


def test_private_use_area_is_flagged():
    garbled = "".join(chr(c) for c in range(0xE000, 0xE000 + 50))
    assert text_garble_ratio(garbled) == 1.0


def test_replacement_and_control_chars_counted():
    # 2 bad (one U+FFFD, one control \x00) out of 10 chars = 0.2
    assert abs(text_garble_ratio("ab�cd\x00efgh") - 0.2) < 1e-9


def test_normal_whitespace_is_not_garble():
    assert text_garble_ratio("line one\nline two\tindented\r\n") == 0.0


# --- pipeline: a broken text layer is warned about, loudly ---------------


def test_pipeline_warns_loudly_on_garbled_page(
    env_with_key, project_root: Path, tmp_path: Path, monkeypatch, capsys
):
    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")

    # Force the detector high so the warning fires deterministically (the synthetic
    # PDF's real text is clean); the wiring is what we're asserting.
    monkeypatch.setattr(pipeline_module, "text_garble_ratio", lambda _t: 0.5)

    pipeline_module.convert(pdf, cfg, tmp_path / "out", client=FakeClient("desc"), quiet=False)

    out = capsys.readouterr().out
    assert "text layer looks broken" in out
    assert "re-export or pre-OCR" in out


def test_pipeline_quiet_on_clean_page(env_with_key, project_root: Path, tmp_path: Path, capsys):
    pdf = synthetic_pdf(tmp_path / "doc.pdf")  # clean synthetic text
    cfg = load_config(project_root / "config.example.yaml")

    pipeline_module.convert(pdf, cfg, tmp_path / "out", client=FakeClient("desc"), quiet=False)

    assert "text layer looks broken" not in capsys.readouterr().out
