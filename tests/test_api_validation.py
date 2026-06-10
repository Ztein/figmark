"""Phase 2: input validation on /v1/convert — each failure is loud and typed."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import API_TEST_TOKEN
from .fakes import FakeClient, synthetic_pdf

AUTH = {"Authorization": f"Bearer {API_TEST_TOKEN}"}


def test_non_pdf_content_type_is_415(make_api_app):
    client = TestClient(make_api_app(FakeClient("desc")))
    r = client.post(
        "/v1/convert",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=AUTH,
    )
    assert r.status_code == 415


def test_pdf_name_but_not_pdf_bytes_is_422(make_api_app):
    client = TestClient(make_api_app(FakeClient("desc")))
    r = client.post(
        "/v1/convert",
        files={"file": ("doc.pdf", b"not really a pdf", "application/pdf")},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_corrupt_pdf_is_422(make_api_app):
    client = TestClient(make_api_app(FakeClient("desc")))
    # Valid header but garbage body — fitz.open should fail.
    r = client.post(
        "/v1/convert",
        files={"file": ("doc.pdf", b"%PDF-1.4 broken broken broken", "application/pdf")},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_oversized_upload_is_413(make_api_app, tmp_path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = TestClient(make_api_app(FakeClient("desc"), max_upload_bytes=1024))
    r = client.post(
        "/v1/convert",
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        headers=AUTH,
    )
    assert r.status_code == 413
