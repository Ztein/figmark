"""Phase 2: health, readiness, and version endpoints (offline)."""

from __future__ import annotations

from fastapi.testclient import TestClient

import figmark.api as api_module
from figmark import __version__

from .fakes import FakeClient


def test_healthz_always_ok(make_api_app):
    client = TestClient(make_api_app(FakeClient("x")))
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_ok_when_tesseract_and_language_present(make_api_app, monkeypatch):
    monkeypatch.setattr(api_module.shutil, "which", lambda _name: "/usr/bin/tesseract")
    monkeypatch.setattr(api_module, "_available_ocr_languages", lambda: ["eng", "swe"])
    client = TestClient(make_api_app(FakeClient("x")))
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["ready"] is True


def test_readyz_503_when_tesseract_missing(make_api_app, monkeypatch):
    monkeypatch.setattr(api_module.shutil, "which", lambda _name: None)
    client = TestClient(make_api_app(FakeClient("x")))
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["ready"] is False
    assert r.json()["checks"]["tesseract"] is False


def test_version_has_no_secrets(make_api_app):
    client = TestClient(make_api_app(FakeClient("x")))
    r = client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == __version__
    assert "model" in body and "base_url" in body
    # No secret material is exposed.
    blob = " ".join(str(v) for v in body.values()).lower()
    assert "token" not in body
    assert "secret-token" not in blob and "berget_api_key" not in blob
