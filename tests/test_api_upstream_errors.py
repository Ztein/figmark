"""T-048: upstream LLM errors map to clean gateway statuses, never leak provider
internals, and don't masquerade as figmark bugs.

Offline: a fake client raises the openai exception the real client would raise, so
CI covers the mapping without a live key.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIStatusError, APITimeoutError, RateLimitError

from .conftest import API_TEST_TOKEN
from .fakes import synthetic_pdf

AUTH = {"Authorization": f"Bearer {API_TEST_TOKEN}"}

# Provider internals that must never reach the client in the response body.
LEAKY = ("WALLET_NOT_SETUP", "corr-leak-123", "req-leak-456", "No subscription found")


class RaisingClient:
    """A client whose first (and every) chat call raises a given exception."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, *args, **kwargs):
        raise self._exc


def _status_error(status_code: int) -> APIStatusError:
    """An openai APIStatusError carrying a leaky provider body, like the real one."""
    request = httpx.Request("POST", "https://upstream.example/v1/chat/completions")
    body = {
        "error": {
            "code": "WALLET_NOT_SETUP",
            "message": "No subscription found for this API key.",
            "correlation_id": "corr-leak-123",
            "request_id": "req-leak-456",
        }
    }
    response = httpx.Response(status_code, request=request, json=body)
    return APIStatusError("No subscription found", response=response, body=body)


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://upstream.example/v1/chat/completions")
    response = httpx.Response(429, request=request, json={"error": {"code": "rate"}})
    return RateLimitError("slow down", response=response, body=None)


def _post(app, tmp_path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = TestClient(app, raise_server_exceptions=False)
    return client.post(
        "/v1/convert", files={"file": ("doc.pdf", pdf, "application/pdf")}, headers=AUTH
    )


def _assert_no_leak(body_text: str) -> None:
    for token in LEAKY:
        assert token not in body_text, f"upstream internal {token!r} leaked to client"


@pytest.mark.parametrize("upstream_status", [401, 402, 403, 500, 503])
def test_bad_key_or_quota_maps_to_502_without_leak(make_api_app, tmp_path, upstream_status):
    app = make_api_app(RaisingClient(_status_error(upstream_status)))
    r = _post(app, tmp_path)
    assert r.status_code == 502
    _assert_no_leak(r.text)
    assert r.json()["detail"] == (
        "LLM backend rejected the request — check the API key, quota, and endpoint"
    )


def test_rate_limit_maps_to_503(make_api_app, tmp_path):
    app = make_api_app(RaisingClient(_rate_limit_error()))
    r = _post(app, tmp_path)
    assert r.status_code == 503
    assert "rate-limiting" in r.json()["detail"]


def test_upstream_timeout_maps_to_504(make_api_app, tmp_path):
    request = httpx.Request("POST", "https://upstream.example/v1/chat/completions")
    app = make_api_app(RaisingClient(APITimeoutError(request)))
    r = _post(app, tmp_path)
    assert r.status_code == 504


def test_genuine_figmark_bug_still_500(make_api_app, tmp_path):
    # A non-LLM exception is not an upstream fault — it must surface as 500, not be
    # masked as a 502 bad gateway.
    app = make_api_app(RaisingClient(ValueError("boom — a real figmark bug")))
    r = _post(app, tmp_path)
    assert r.status_code == 500
