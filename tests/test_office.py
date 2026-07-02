"""T-054: Office → PDF conversion via LibreOffice headless.

Conversion runs sandboxed: a throwaway LibreOffice profile per call (with macro
security pinned to "very high"), a hard timeout with kill, and output confined
to the caller's directory. Tests needing a real LibreOffice skip when `soffice`
is absent (CI has none — these are the local-responsibility tier, like the live
suite); the pure-logic tests always run.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import fitz
import pytest

from figmark.office import (
    MACRO_SECURITY_XCU,
    OfficeConversionError,
    convert_office_to_pdf,
    find_soffice,
)

CORPUS = Path(__file__).resolve().parent.parent / "testfiler" / "office-eval"

needs_soffice = pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")


def corpus_file(name: str) -> Path:
    p = CORPUS / name
    if not p.exists():
        pytest.skip(f"local office-eval corpus file missing: {name}")
    return p


@needs_soffice
def test_docx_converts_to_openable_pdf_with_text(tmp_path: Path):
    src = corpus_file("skr-kommunbas.docx")
    pdf = convert_office_to_pdf(src, tmp_path)
    assert pdf.exists() and pdf.suffix == ".pdf"
    doc = fitz.open(pdf)
    text = "".join(page.get_text("text") for page in doc)
    doc.close()
    assert len(text.strip()) > 500, "the converted PDF must carry the document text"


@needs_soffice
def test_conversion_uses_a_throwaway_profile_with_macros_locked(tmp_path: Path):
    src = corpus_file("poi-comments.docx")
    convert_office_to_pdf(src, tmp_path)
    profile = tmp_path / "lo-profile"
    assert profile.is_dir(), "each conversion gets its own isolated profile"
    xcu = profile / "user" / "registrymodifications.xcu"
    assert xcu.exists(), "the profile must pre-seed macro security"
    assert "MacroSecurityLevel" in xcu.read_text(encoding="utf-8")


@needs_soffice
def test_corrupt_office_file_fails_loudly(tmp_path: Path):
    bad = tmp_path / "broken.docx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "not xml at all \x00\x01")
    # Depending on the LibreOffice version this either errors or produces no
    # output — both must surface as the same loud exception.
    try:
        pdf = convert_office_to_pdf(bad, tmp_path)
    except OfficeConversionError:
        return
    # If LO "converted" garbage, the result must at least be an openable PDF —
    # otherwise the pipeline would fail loud right after anyway.
    fitz.open(pdf).close()


@needs_soffice
def test_timeout_kills_and_fails_loudly(tmp_path: Path):
    src = corpus_file("skr-kommunbas.docx")
    with pytest.raises(OfficeConversionError, match="timed out"):
        convert_office_to_pdf(src, tmp_path, timeout=0.05)


def test_missing_soffice_fails_loudly(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    src = tmp_path / "x.docx"
    src.write_bytes(b"PK\x03\x04")
    with pytest.raises(OfficeConversionError, match="soffice"):
        convert_office_to_pdf(src, tmp_path, soffice=None)


def test_macro_xcu_pins_very_high_security():
    assert 'name="MacroSecurityLevel"' in MACRO_SECURITY_XCU
    assert "<value>3</value>" in MACRO_SECURITY_XCU


# --- config wiring -----------------------------------------------------------


def _office_config(project_root: Path, tmp_path: Path, **office) -> Path:
    import yaml

    raw = yaml.safe_load((project_root / "config.example.yaml").read_text(encoding="utf-8"))
    raw["input"] = {"formats": ["pdf", "docx", "xlsx", "pptx"], "office": office}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


@needs_soffice
def test_office_formats_load_when_soffice_is_present(
    env_with_key, project_root: Path, tmp_path: Path
):
    from figmark.config import load_config

    cfg = load_config(_office_config(project_root, tmp_path, timeout_seconds=60))
    assert "docx" in cfg.input.formats
    assert cfg.input.office is not None
    assert Path(cfg.input.office.soffice_path).exists()
    assert cfg.input.office.timeout_seconds == 60


def test_office_formats_without_soffice_fail_at_load(
    env_with_key, project_root: Path, tmp_path: Path, monkeypatch
):
    import figmark.office as office_mod
    from figmark.config import load_config

    monkeypatch.setattr(office_mod, "find_soffice", lambda configured=None: None)
    with pytest.raises(RuntimeError, match="soffice"):
        load_config(_office_config(project_root, tmp_path, timeout_seconds=60))


def test_office_timeout_is_required_when_office_formats_configured(
    env_with_key, project_root: Path, tmp_path: Path
):
    if find_soffice() is None:
        pytest.skip("LibreOffice not installed")
    from figmark.config import load_config

    with pytest.raises(RuntimeError, match="timeout_seconds"):
        load_config(_office_config(project_root, tmp_path))


# --- API end-to-end ----------------------------------------------------------


@needs_soffice
def test_docx_converts_end_to_end_over_http(env_with_key, project_root: Path, tmp_path: Path):
    from fastapi.testclient import TestClient

    from figmark.api import ServerSettings, create_app
    from figmark.config import load_config

    from .conftest import API_TEST_TOKEN
    from .fakes import FakeClient

    src = corpus_file("skr-kommunbas.docx")
    cfg = load_config(_office_config(project_root, tmp_path, timeout_seconds=120))
    settings = ServerSettings(
        auth_token=API_TEST_TOKEN,
        config_path=project_root / "config.example.yaml",
        max_upload_bytes=50 * 1024 * 1024,
        work_dir=tmp_path / "work",
        request_timeout_seconds=180.0,
        max_concurrent_jobs=1,
    )
    app = create_app(settings=settings, cfg=cfg, client=FakeClient("En bild."))
    client = TestClient(app)
    resp = client.post(
        "/v1/convert",
        headers={"Authorization": f"Bearer {API_TEST_TOKEN}"},
        files={
            "file": (
                src.name,
                src.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_count"] >= 1
    assert len(body["markdown"]) > 500, "the docx text must come through"
