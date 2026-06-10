"""Phase 2: the convert endpoint end-to-end with an injected fake client."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import API_TEST_TOKEN
from .fakes import DETECTED_LANGUAGE, FakeClient, synthetic_pdf

AUTH = {"Authorization": f"Bearer {API_TEST_TOKEN}"}


def test_convert_returns_markdown(make_api_app, tmp_path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = TestClient(make_api_app(FakeClient("En bild på en katt.")))
    r = client.post(
        "/v1/convert", files={"file": ("doc.pdf", pdf, "application/pdf")}, headers=AUTH
    )
    assert r.status_code == 200
    body = r.json()
    assert "En bild på en katt." in body["markdown"]
    assert body["page_count"] == 1
    assert body["figure_count"] == 1
    assert body["skipped_count"] == 0
    assert body["language"] == DETECTED_LANGUAGE


def test_convert_skip_marker_drops_image(make_api_app, tmp_path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = TestClient(make_api_app(FakeClient("[SKIP]")))
    r = client.post(
        "/v1/convert", files={"file": ("doc.pdf", pdf, "application/pdf")}, headers=AUTH
    )
    assert r.status_code == 200
    body = r.json()
    assert body["figure_count"] == 0
    assert body["skipped_count"] == 1
    assert "](images/" not in body["markdown"]
