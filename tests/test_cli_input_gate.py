"""T-066: the CLI gates its input like the HTTP surface — never a silent empty run.

`figmark <file>` used to hand any path straight to PyMuPDF, which "opens" an
Office file as a degraded near-empty document and exits 0. The gate is now the
same transport-neutral check the HTTP handlers use (sniff → allowlist →
mismatch detection), so the CLI converts what the service converts and refuses
what the service refuses — loudly, with a non-zero exit.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from figmark.main import main
from figmark.office import find_soffice

from .fakes import FakeClient, synthetic_pdf

needs_soffice = pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")


def fake_pptx(path: Path) -> Path:
    """A minimal OOXML presentation container — sniffs as 'pptx'."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
    return path


def run_cli(doc: Path, config: Path, out: Path) -> int:
    return main([str(doc), "--config", str(config), "--output", str(out)])


def test_office_file_is_refused_loudly_when_not_enabled(
    env_with_key, project_root: Path, tmp_path: Path, capsys
):
    """The exact T-066 symptom: a .pptx must NOT complete as an empty exit-0
    run. With Office formats not in the allowlist it is refused, naming the
    format and the supported set, plus a remedy hint."""
    doc = fake_pptx(tmp_path / "deck.pptx")
    rc = run_cli(doc, project_root / "config.example.yaml", tmp_path / "out")
    assert rc != 0
    err = capsys.readouterr().err
    assert "pptx" in err and "Supported formats" in err
    assert "hint" in err, "the refusal must name the remedy"
    assert not (tmp_path / "out").exists(), "no confident empty output is produced"


def test_extension_content_mismatch_is_refused(
    env_with_key, project_root: Path, tmp_path: Path, capsys
):
    """A file whose name claims .pdf but whose bytes are something else must be
    refused as a mismatch — this is the mislabeled/truncated-input floor."""
    doc = tmp_path / "report.pdf"
    doc.write_bytes(b"not a pdf at all")
    rc = run_cli(doc, project_root / "config.example.yaml", tmp_path / "out")
    assert rc != 0
    assert "claims 'pdf'" in capsys.readouterr().err


def test_unknown_extension_is_refused(env_with_key, project_root: Path, tmp_path: Path, capsys):
    doc = tmp_path / "notes.txt"
    doc.write_text("hello")
    rc = run_cli(doc, project_root / "config.example.yaml", tmp_path / "out")
    assert rc != 0
    assert "'.txt'" in capsys.readouterr().err


def test_pdf_still_converts_through_the_gate(
    env_with_key, project_root: Path, tmp_path: Path, monkeypatch
):
    """The gate must not get in the way of the happy path."""
    import figmark.main as main_mod

    monkeypatch.setattr(main_mod, "make_client", lambda cfg: FakeClient("En bild."))
    doc = synthetic_pdf(tmp_path / "doc.pdf")
    rc = run_cli(doc, project_root / "config.example.yaml", tmp_path / "out")
    assert rc == 0
    md = next((tmp_path / "out").rglob("*.md"))
    assert md.read_text(encoding="utf-8").strip()


@needs_soffice
def test_office_file_converts_with_http_parity_when_enabled(
    env_with_key, project_root: Path, tmp_path: Path, monkeypatch
):
    """With Office formats enabled (and LibreOffice present), the CLI takes the
    same convert-to-PDF path as the HTTP surface instead of silently
    under-extracting."""
    import figmark.main as main_mod

    corpus = project_root / "testfiler" / "office-eval" / "poi-bar-chart.pptx"
    if not corpus.exists():
        pytest.skip("local office-eval corpus file missing: poi-bar-chart.pptx")

    cfg_text = (project_root / "config.example.yaml").read_text(encoding="utf-8")
    cfg_text = cfg_text.replace("    - pdf\n    - epub\n", "    - pdf\n    - epub\n    - pptx\n")
    cfg_text = cfg_text.replace(
        "  # office:\n  #   timeout_seconds: 120", "  office:\n    timeout_seconds: 120"
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(cfg_text, encoding="utf-8")

    monkeypatch.setattr(main_mod, "make_client", lambda cfg: FakeClient("Ett stapeldiagram."))
    rc = run_cli(corpus, cfg_path, tmp_path / "out")
    assert rc == 0
    md = next((tmp_path / "out").rglob("*.md")).read_text(encoding="utf-8")
    assert md.strip(), "the converted deck must produce real content"
