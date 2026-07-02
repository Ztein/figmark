"""T-054: the HTTP input gate — allowlist enforcement + content sniffing.

Both surfaces (/v1/convert multipart and /v1/ocr Mistral-compat) must accept
exactly the configured formats, reject everything else with a clean 415 that
names the supported set, and fail loud (422) on an extension/content mismatch
instead of mis-handling the bytes.
"""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from .conftest import API_TEST_TOKEN
from .fakes import FakeClient
from .test_input_formats import OLE_MAGIC, make_mini_epub, make_ooxml_zip

AUTH = {"Authorization": f"Bearer {API_TEST_TOKEN}"}

EPUB_PROSE = "Unmistakable epub sentence about foxes. " * 30


def _client(make_api_app) -> TestClient:
    return TestClient(make_api_app(FakeClient("En bild.")))


def _post_file(client: TestClient, name: str, payload: bytes, ctype: str):
    return client.post("/v1/convert", headers=AUTH, files={"file": (name, payload, ctype)})


def test_epub_converts_end_to_end(make_api_app, tmp_path: Path):
    epub = make_mini_epub(tmp_path / "book.epub", body_text=EPUB_PROSE).read_bytes()
    resp = _post_file(_client(make_api_app), "book.epub", epub, "application/epub+zip")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "Unmistakable epub sentence about foxes." in body["markdown"]
    assert body["page_count"] >= 1


def test_disallowed_format_gets_415_naming_the_supported_set(make_api_app, tmp_path: Path):
    docx = make_ooxml_zip(tmp_path / "doc.docx", "docx").read_bytes()
    resp = _post_file(
        _client(make_api_app),
        "doc.docx",
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert resp.status_code == 415
    detail = resp.json()["detail"]
    assert "docx" in detail, "the rejected format is named"
    assert "pdf" in detail and "epub" in detail, "the supported set is named"


def test_legacy_ole_office_gets_a_targeted_415(make_api_app):
    resp = _post_file(
        _client(make_api_app), "old.doc", OLE_MAGIC + b"\x00" * 512, "application/msword"
    )
    assert resp.status_code == 415
    assert "legacy" in resp.json()["detail"].lower()


def test_extension_content_mismatch_fails_loudly(make_api_app, tmp_path: Path):
    """Bytes are a docx but the name claims .pdf — 422 naming both, never mis-handled."""
    docx = make_ooxml_zip(tmp_path / "x.bin", "docx").read_bytes()
    resp = _post_file(_client(make_api_app), "report.pdf", docx, "application/pdf")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "pdf" in detail and "docx" in detail


def test_unidentifiable_bytes_get_422(make_api_app):
    resp = _post_file(_client(make_api_app), "junk.epub", b"not a container at all", "")
    assert resp.status_code == 422


def test_plain_pdf_still_works(make_api_app, tmp_path: Path):
    from .test_input_formats import make_pdf

    pdf = make_pdf(tmp_path / "x.pdf").read_bytes()
    resp = _post_file(_client(make_api_app), "x.pdf", pdf, "application/pdf")
    assert resp.status_code == 200, resp.text


# --- /v1/ocr (Mistral-compat, T-052) ----------------------------------------


def _post_ocr(client: TestClient, payload: bytes, mime: str):
    data_url = f"data:{mime};base64," + base64.b64encode(payload).decode()
    return client.post(
        "/v1/ocr",
        headers=AUTH,
        json={"document": {"type": "document_url", "document_url": data_url}},
    )


def test_ocr_accepts_epub(make_api_app, tmp_path: Path):
    epub = make_mini_epub(tmp_path / "book.epub", body_text=EPUB_PROSE).read_bytes()
    resp = _post_ocr(_client(make_api_app), epub, "application/epub+zip")
    assert resp.status_code == 200, resp.text
    pages = resp.json()["pages"]
    assert any("Unmistakable epub sentence" in p["markdown"] for p in pages)


def test_ocr_rejects_disallowed_format_naming_the_set(make_api_app, tmp_path: Path):
    docx = make_ooxml_zip(tmp_path / "d.docx", "docx").read_bytes()
    resp = _post_ocr(_client(make_api_app), docx, "application/octet-stream")
    assert resp.status_code == 415
    detail = resp.json()["detail"]
    assert "docx" in detail and "pdf" in detail and "epub" in detail
