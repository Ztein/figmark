"""Phase 2: bearer-token auth on /v1/convert (offline)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from .conftest import API_TEST_TOKEN
from .fakes import FakeClient, synthetic_pdf


def _pdf_bytes(tmp_path: Path) -> bytes:
    return synthetic_pdf(tmp_path / "doc.pdf").read_bytes()


def _post(client, pdf: bytes, headers=None):
    return client.post(
        "/v1/convert",
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        headers=headers or {},
    )


def test_missing_token_is_401(make_api_app, tmp_path):
    client = TestClient(make_api_app(FakeClient("desc")))
    assert _post(client, _pdf_bytes(tmp_path)).status_code == 401


def test_wrong_token_is_401(make_api_app, tmp_path):
    client = TestClient(make_api_app(FakeClient("desc")))
    r = _post(client, _pdf_bytes(tmp_path), {"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_wrong_length_token_is_401(make_api_app, tmp_path):
    # constant-time compare must still reject regardless of length
    client = TestClient(make_api_app(FakeClient("desc")))
    r = _post(client, _pdf_bytes(tmp_path), {"Authorization": "Bearer x"})
    assert r.status_code == 401


def test_correct_token_is_200(make_api_app, tmp_path):
    client = TestClient(make_api_app(FakeClient("En bild på en katt.")))
    r = _post(client, _pdf_bytes(tmp_path), {"Authorization": f"Bearer {API_TEST_TOKEN}"})
    assert r.status_code == 200
