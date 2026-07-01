"""LibreChat / Mistral-OCR-compatible surface (T-052).

Drives the same four-call flow LibreChat's default strategy uses — upload → signed
URL → /v1/ocr → delete — against the app with an injected fake client, plus the
auth, signature, and input-validation edge cases.
"""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from figmark.ocr_compat import split_pages

from .conftest import API_TEST_TOKEN
from .fakes import FakeClient, synthetic_pdf

AUTH = {"Authorization": f"Bearer {API_TEST_TOKEN}"}
DESC = "En bild på en katt."


def _client(make_api_app):
    return TestClient(make_api_app(FakeClient(DESC)))


def _pdf_bytes(tmp_path):
    return synthetic_pdf(tmp_path / "doc.pdf").read_bytes()


def test_full_mistral_flow_roundtrips(make_api_app, tmp_path):
    """upload → signed URL → /v1/ocr → delete, the LibreChat default path."""
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)

    # 1. POST /v1/files
    up = client.post(
        "/v1/files",
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        data={"purpose": "ocr"},
        headers=AUTH,
    )
    assert up.status_code == 200, up.text
    file_id = up.json()["id"]
    assert up.json()["bytes"] == len(pdf)

    # 2. GET /v1/files/{id}/url
    signed = client.get(f"/v1/files/{file_id}/url", params={"expiry": 24}, headers=AUTH)
    assert signed.status_code == 200
    url = signed.json()["url"]
    assert f"/v1/files/{file_id}/content" in url and "sig=" in url

    # 3. POST /v1/ocr referencing that signed URL
    ocr = client.post(
        "/v1/ocr",
        json={
            "model": "mistral-ocr-latest",
            "include_image_base64": False,
            "document": {"type": "document_url", "document_url": url},
        },
        headers=AUTH,
    )
    assert ocr.status_code == 200, ocr.text
    payload = ocr.json()
    assert payload["pages"], "expected at least one page"
    assert payload["pages"][0]["index"] == 0
    assert DESC in payload["pages"][0]["markdown"]
    assert payload["pages"][0]["images"] == []
    assert payload["usage_info"]["pages_processed"] == 1
    assert payload["usage_info"]["doc_size_bytes"] == len(pdf)

    # 4. DELETE /v1/files/{id}
    dele = client.delete(f"/v1/files/{file_id}", headers=AUTH)
    assert dele.status_code == 200 and dele.json()["deleted"] is True

    # The file is gone: a fresh /v1/ocr against the same URL now 404s.
    gone = client.post(
        "/v1/ocr",
        json={"document": {"type": "document_url", "document_url": url}},
        headers=AUTH,
    )
    assert gone.status_code == 404


def test_ocr_accepts_inline_data_url(make_api_app, tmp_path):
    """The Azure-variant path: base64 PDF inline in the document URL."""
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode()
    r = client.post(
        "/v1/ocr",
        json={"document": {"type": "document_url", "document_url": data_url}},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    assert DESC in r.json()["pages"][0]["markdown"]


def test_non_pdf_data_url_is_415(make_api_app):
    client = _client(make_api_app)
    data_url = "data:text/plain;base64," + base64.b64encode(b"just text").decode()
    r = client.post(
        "/v1/ocr",
        json={"document": {"type": "document_url", "document_url": data_url}},
        headers=AUTH,
    )
    assert r.status_code == 415


def test_external_url_is_rejected(make_api_app):
    client = _client(make_api_app)
    r = client.post(
        "/v1/ocr",
        json={"document": {"type": "document_url", "document_url": "https://evil.example/x.pdf"}},
        headers=AUTH,
    )
    assert r.status_code == 400


def test_tampered_signature_is_403(make_api_app, tmp_path):
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    file_id = client.post(
        "/v1/files", files={"file": ("doc.pdf", pdf, "application/pdf")}, headers=AUTH
    ).json()["id"]
    url = client.get(f"/v1/files/{file_id}/url", headers=AUTH).json()["url"]
    tampered = url.rsplit("sig=", 1)[0] + "sig=deadbeef"
    r = client.post(
        "/v1/ocr",
        json={"document": {"type": "document_url", "document_url": tampered}},
        headers=AUTH,
    )
    assert r.status_code == 403


def test_content_endpoint_serves_bytes_with_valid_sig(make_api_app, tmp_path):
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    file_id = client.post(
        "/v1/files", files={"file": ("doc.pdf", pdf, "application/pdf")}, headers=AUTH
    ).json()["id"]
    url = client.get(f"/v1/files/{file_id}/url", headers=AUTH).json()["url"]
    # The signed content URL is self-authenticating (no bearer needed).
    ok = client.get(url)
    assert ok.status_code == 200 and ok.content == pdf
    bad = client.get(f"/v1/files/{file_id}/content?sig=nope")
    assert bad.status_code == 403


def test_ocr_and_files_require_auth(make_api_app, tmp_path):
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    assert client.post("/v1/ocr", json={"document": {}}).status_code == 401
    assert (
        client.post("/v1/files", files={"file": ("doc.pdf", pdf, "application/pdf")}).status_code
        == 401
    )
    assert client.get("/v1/files/abc/url").status_code == 401
    assert client.delete("/v1/files/abc").status_code == 401


def test_split_pages_uses_page_markers():
    md = "<!-- page 1 -->\nHello\n\n<!-- page 2 -->\nWorld\n"
    pages = split_pages(md)
    assert [p["index"] for p in pages] == [0, 1]
    assert pages[0]["markdown"] == "Hello"
    assert pages[1]["markdown"] == "World"
    # No marker → single page with the whole body.
    assert split_pages("just text")[0]["markdown"] == "just text"
