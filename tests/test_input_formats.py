"""T-054: content sniffing + the configurable input-format allowlist.

Format detection must look at what the bytes actually are (magic numbers, then
container inspection — OOXML and EPUB are both ZIP), never the filename alone.
The synthetic builders here keep CI self-contained; when the local office-eval
corpus is present (testfiler/office-eval/, gitignored) the sniffer is also run
against every real file in it.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import yaml

from figmark.config import load_config
from figmark.input_formats import (
    NATIVE_FORMATS,
    OFFICE_FORMATS,
    SUPPORTED_FORMATS,
    sniff_format,
)

CORPUS = Path(__file__).resolve().parent.parent / "testfiler" / "office-eval"

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def make_mini_epub(path: Path, body_text: str = "Plain epub prose. " * 30) -> Path:
    """A minimal but valid EPUB 2 that PyMuPDF can open."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>\n'
            '<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles>\n'
            "</container>",
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" '
            'unique-identifier="id" version="2.0">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            "    <dc:title>Mini Test Book</dc:title><dc:language>en</dc:language>\n"
            '    <dc:identifier id="id">mini-test-1</dc:identifier>\n'
            "  </metadata>\n"
            '  <manifest><item id="c1" href="chapter1.xhtml" '
            'media-type="application/xhtml+xml"/></manifest>\n'
            '  <spine><itemref idref="c1"/></spine>\n'
            "</package>",
        )
        z.writestr(
            "OEBPS/chapter1.xhtml",
            '<?xml version="1.0"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ch1</title></head>\n'
            f"<body><h1>Chapter One</h1><p>{body_text}</p></body></html>",
        )
    return path


def make_ooxml_zip(path: Path, kind: str) -> Path:
    """The smallest ZIP that carries a given OOXML flavour's marker part."""
    marker = {
        "docx": "word/document.xml",
        "xlsx": "xl/workbook.xml",
        "pptx": "ppt/presentation.xml",
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(marker[kind], "<root/>")
    return path


def make_pdf(path: Path) -> Path:
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "hello")
    doc.save(path)
    doc.close()
    return path


# --- sniffing ---------------------------------------------------------------


def test_sniffs_pdf(tmp_path: Path):
    assert sniff_format(make_pdf(tmp_path / "x.bin")) == "pdf"


def test_sniffs_epub(tmp_path: Path):
    assert sniff_format(make_mini_epub(tmp_path / "x.bin")) == "epub"


@pytest.mark.parametrize("kind", ["docx", "xlsx", "pptx"])
def test_sniffs_ooxml(tmp_path: Path, kind: str):
    assert sniff_format(make_ooxml_zip(tmp_path / "x.bin", kind)) == kind


def test_sniffs_legacy_ole_office(tmp_path: Path):
    p = tmp_path / "x.bin"
    p.write_bytes(OLE_MAGIC + b"\x00" * 512)
    assert sniff_format(p) == "ole"


def test_unknown_bytes_sniff_to_none(tmp_path: Path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"this is just text, not a document container")
    assert sniff_format(p) is None


def test_unmarked_zip_sniffs_to_none(tmp_path: Path):
    p = tmp_path / "x.bin"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("random.txt", "nothing document-like")
    assert sniff_format(p) is None


def test_truncated_zip_sniffs_to_none(tmp_path: Path):
    """A ZIP signature with a broken body must not crash the sniffer."""
    p = tmp_path / "x.bin"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 20)
    assert sniff_format(p) is None


@pytest.mark.parametrize(
    "file",
    sorted(CORPUS.glob("*.*")) if CORPUS.is_dir() else [],
    ids=lambda f: f.name,
)
def test_sniffs_real_corpus_files(file: Path):
    """Every real office-eval corpus file sniffs to its own extension."""
    if file.suffix in (".yaml", ".md"):
        pytest.skip("corpus metadata, not a document")
    assert sniff_format(file) == file.suffix.lstrip(".")


def test_corpus_present_or_skipped():
    if not CORPUS.is_dir():
        pytest.skip("local office-eval corpus not present (testfiler/office-eval/)")


# --- config allowlist -------------------------------------------------------


def _config_with_input(project_root: Path, tmp_path: Path, formats) -> Path:
    raw = yaml.safe_load((project_root / "config.example.yaml").read_text(encoding="utf-8"))
    raw["input"] = {"formats": formats}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_example_config_declares_input_formats(env_with_key, project_root: Path):
    cfg = load_config(project_root / "config.example.yaml")
    assert "pdf" in cfg.input.formats
    assert "epub" in cfg.input.formats
    assert set(cfg.input.formats) <= SUPPORTED_FORMATS


def test_missing_input_section_fails_loudly(env_with_key, project_root: Path, tmp_path: Path):
    raw = yaml.safe_load((project_root / "config.example.yaml").read_text(encoding="utf-8"))
    del raw["input"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(RuntimeError, match="input"):
        load_config(path)


def test_unknown_format_fails_loudly(env_with_key, project_root: Path, tmp_path: Path):
    path = _config_with_input(project_root, tmp_path, ["pdf", "wordperfect"])
    with pytest.raises(RuntimeError, match="wordperfect"):
        load_config(path)


def test_office_format_without_office_support_fails_loudly(
    env_with_key, project_root: Path, tmp_path: Path
):
    """Allowlisting docx/xlsx/pptx needs the LibreOffice conversion path — until it
    exists (T-054 PR2), declaring one must fail at load, not 500 at request time."""
    path = _config_with_input(project_root, tmp_path, ["pdf", "docx"])
    with pytest.raises(RuntimeError, match="docx"):
        load_config(path)


def test_empty_format_list_fails_loudly(env_with_key, project_root: Path, tmp_path: Path):
    path = _config_with_input(project_root, tmp_path, [])
    with pytest.raises(RuntimeError, match="input.formats"):
        load_config(path)


def test_registry_is_coherent():
    assert NATIVE_FORMATS & OFFICE_FORMATS == set()
    assert SUPPORTED_FORMATS == NATIVE_FORMATS | OFFICE_FORMATS
    assert "pdf" in NATIVE_FORMATS and "epub" in NATIVE_FORMATS
    assert {"docx", "xlsx", "pptx"} == OFFICE_FORMATS
