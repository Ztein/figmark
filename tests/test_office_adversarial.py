"""T-054: adversarial Office input — hostile documents are rejected or contained.

The Office path hands untrusted bytes to LibreOffice, so the sandbox claims
must be *asserted*, not assumed: macro-carrying, DDE-launching,
external-reference, decompression-bomb and truncated inputs must either fail
loudly (OfficeConversionError) or convert safely — never execute anything,
never hang past the timeout.

Every hostile file is GENERATED here (OOXML is just a zip of XML — no
authoring dependency, nothing hostile hosted in the repo). Tests need a local
LibreOffice and are marked `office`; they skip loudly when soffice is absent.
"""

from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path

import pytest

from figmark.office import OfficeConversionError, convert_office_to_pdf

pytestmark = pytest.mark.office

requires_soffice = pytest.mark.skipif(
    shutil.which("soffice") is None, reason="LibreOffice (soffice) not on PATH"
)

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="{main_ct}"/>
  {extra_overrides}
</Types>
"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

_DOC_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}</w:body>
</w:document>
"""

_DOCX_MAIN_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_DOCM_MAIN_CT = "application/vnd.ms-word.document.macroEnabled.main+xml"


def _paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _make_docx(
    path: Path,
    body: str,
    *,
    main_ct: str = _DOCX_MAIN_CT,
    extra_overrides: str = "",
    extra_files: dict[str, bytes] | None = None,
    document_rels: str | None = None,
) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            _CONTENT_TYPES.format(main_ct=main_ct, extra_overrides=extra_overrides),
        )
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("word/document.xml", _DOC_XML.format(body=body))
        if document_rels is not None:
            z.writestr("word/_rels/document.xml.rels", document_rels)
        for name, data in (extra_files or {}).items():
            z.writestr(name, data)
    return path


@requires_soffice
def test_benign_generated_docx_converts(tmp_path: Path):
    """Sanity: the generator itself produces something LibreOffice accepts."""
    doc = _make_docx(tmp_path / "benign.docx", _paragraph("Hello from the corpus."))
    pdf = convert_office_to_pdf(doc, tmp_path / "out", timeout=60)
    assert pdf.is_file() and pdf.stat().st_size > 0


@requires_soffice
def test_dde_field_does_not_execute(tmp_path: Path):
    """A DDEAUTO field naming a shell command must never run it (canary file)."""
    canary = tmp_path / "pwned-by-dde"
    body = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> DDEAUTO /bin/sh "-c" '
        f'"touch {canary}" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>field result</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    ) + _paragraph("Body text after the field.")
    doc = _make_docx(tmp_path / "dde.docx", body)
    try:
        pdf = convert_office_to_pdf(doc, tmp_path / "out", timeout=60)
        assert pdf.is_file()
    except OfficeConversionError:
        pass  # rejecting it outright is also safe
    assert not canary.exists(), "DDE command executed — sandbox breach"


@requires_soffice
def test_macro_enabled_document_is_contained(tmp_path: Path):
    """A macro-carrying (docm-shaped) file converts or fails loudly — the
    macro-locked profile means nothing runs either way."""
    doc = _make_docx(
        tmp_path / "macro.docx",
        _paragraph("Macro carrier."),
        main_ct=_DOCM_MAIN_CT,
        extra_overrides=(
            '<Override PartName="/word/vbaProject.bin" '
            'ContentType="application/vnd.ms-office.vbaProject"/>'
        ),
        extra_files={"word/vbaProject.bin": b"\xd0\xcf\x11\xe0" + b"\x00" * 512},
    )
    try:
        pdf = convert_office_to_pdf(doc, tmp_path / "out", timeout=60)
        assert pdf.is_file()
    except OfficeConversionError:
        pass


@requires_soffice
def test_external_reference_converts_without_network_dependence(tmp_path: Path):
    """An externally-linked image (dead localhost target) must not block or
    fail the conversion — no outbound fetch is required to produce the PDF."""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="http://127.0.0.1:9/never-there.png" TargetMode="External"/>
</Relationships>
"""
    body = _paragraph("Before the external image.") + (
        '<w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/'
        'drawingml/2006/wordprocessingDrawing"><wp:extent cx="914400" cy="914400"/>'
        "</wp:inline></w:drawing></w:r></w:p>"
    )
    doc = _make_docx(tmp_path / "extref.docx", body, document_rels=rels)
    start = time.monotonic()
    try:
        pdf = convert_office_to_pdf(doc, tmp_path / "out", timeout=60)
        assert pdf.is_file()
    except OfficeConversionError:
        pass
    assert time.monotonic() - start < 60, "conversion must not stall on the dead link"


@requires_soffice
def test_decompression_bomb_is_bounded_by_the_timeout(tmp_path: Path):
    """A tiny zip inflating to a huge XML must end within the hard timeout —
    converted, rejected, or killed; never an unbounded hang."""
    # ~200 MB of whitespace inside the body text compresses to well under 1 MB.
    bomb_body = _paragraph("x" * 100 + " " * 200_000_000)
    doc = _make_docx(tmp_path / "bomb.docx", bomb_body)
    assert doc.stat().st_size < 5_000_000, "the bomb itself must be small on disk"
    timeout = 30
    start = time.monotonic()
    try:
        convert_office_to_pdf(doc, tmp_path / "out", timeout=timeout)
    except OfficeConversionError:
        pass  # killed or rejected — both are contained
    assert time.monotonic() - start < timeout + 15, "hard timeout must bound the run"


@requires_soffice
def test_truncated_file_fails_loud(tmp_path: Path):
    intact = _make_docx(tmp_path / "intact.docx", _paragraph("Will be truncated."))
    data = intact.read_bytes()
    truncated = tmp_path / "trunc.docx"
    truncated.write_bytes(data[: len(data) // 2])
    with pytest.raises(OfficeConversionError):
        convert_office_to_pdf(truncated, tmp_path / "out", timeout=60)
