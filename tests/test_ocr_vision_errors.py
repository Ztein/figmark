"""Vision-OCR failure handling: a scanned page that is too large for (or rejected
by) the vision model fails loud with an actionable, page-specific message — never a
bare provider 413, an empty string, or a misleading generic 502.

Offline: a fake client raises/returns what the real client would; the page-image
payload cap is exercised by shrinking the cap, not by crafting a huge image.
"""

from __future__ import annotations

from types import SimpleNamespace

import fitz
import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIStatusError
from PIL import Image

from figmark.config import load_config
from figmark.ocr import VisionOCRError, _encode_page_under_cap, ocr_page_with_vision

from .conftest import API_TEST_TOKEN
from .fakes import FakeClient, synthetic_pdf

AUTH = {"Authorization": f"Bearer {API_TEST_TOKEN}"}


@pytest.fixture
def cfg(project_root):
    return load_config(project_root / "config.example.yaml")


def _blank_page() -> fitz.Page:
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    return doc[0]


class _RaisingClient:
    def __init__(self, exc: Exception):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._exc = exc

    def _create(self, *args, **kwargs):
        raise self._exc


class _EmptyClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, *args, **kwargs):
        message = SimpleNamespace(content="")
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def _api_error(status: int = 413) -> APIStatusError:
    request = httpx.Request("POST", "https://upstream.example/v1/chat/completions")
    response = httpx.Response(status, request=request, json={"error": {"code": "too_large"}})
    return APIStatusError("payload too large", response=response, body=None)


# --- the payload cap ---------------------------------------------------------


def test_encode_under_cap_returns_bytes_for_a_small_page():
    img = Image.new("RGB", (300, 300), "white")
    assert _encode_page_under_cap(img, page_num=1)  # no raise, non-empty


def test_over_cap_page_raises_actionable_error(monkeypatch):
    # Shrink the cap so any real JPEG exceeds it → deterministic failure.
    monkeypatch.setattr("figmark.ocr.MAX_PAYLOAD_BYTES", 10)
    img = Image.new("RGB", (800, 800), "white")
    with pytest.raises(VisionOCRError) as ei:
        _encode_page_under_cap(img, page_num=7)
    msg = str(ei.value)
    assert "page 7" in msg
    assert "render DPI" in msg  # the remedy is named
    assert ei.value.page_num == 7


# --- the vision call ---------------------------------------------------------


def test_rejected_page_wraps_into_vision_ocr_error(cfg):
    page = _blank_page()
    with pytest.raises(VisionOCRError) as ei:
        ocr_page_with_vision(page, _RaisingClient(_api_error(413)), cfg, page_num=3)
    msg = str(ei.value)
    assert "page 3" in msg
    assert "rejected" in msg
    assert "HTTP 413" in msg
    # No provider body leaks (T-048): only figmark-authored context.
    assert "too_large" not in msg


def test_empty_completion_raises_vision_ocr_error(cfg):
    page = _blank_page()
    with pytest.raises(VisionOCRError) as ei:
        ocr_page_with_vision(page, _EmptyClient(), cfg, page_num=2)
    assert "page 2" in str(ei.value)
    assert "no text" in str(ei.value)


# --- the API mapping ---------------------------------------------------------


def test_vision_ocr_error_maps_to_422(make_api_app, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise VisionOCRError(4, "the rendered page is still 1200 KB after maximum downscaling …")

    monkeypatch.setattr("figmark.api.convert", boom)
    app = make_api_app(FakeClient("unused"))
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post(
        "/v1/convert", files={"file": ("doc.pdf", pdf, "application/pdf")}, headers=AUTH
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "page 4" in detail
    assert "downscaling" in detail
