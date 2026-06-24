"""Selectable response format on /v1/convert (T-025).

The format-shaping logic is unit-tested directly (no TestClient needed); a
TestClient integration test exercises the wire path end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient

from figmark.api import ConvertResponse, format_convert_result
from figmark.pipeline import ConversionResult
from figmark.usage import Usage

from .conftest import API_TEST_TOKEN
from .fakes import FakeClient, synthetic_pdf


def _result(estimated_cost=None, currency=None) -> ConversionResult:
    return ConversionResult(
        markdown="# Title\n\nBody text.",
        markdown_path=Path("out.md"),
        raw_text_path=Path("raw.txt"),
        output_dir=Path("out"),
        images_dir=Path("out/images"),
        annotated_pdf_path=None,
        tagged_pdf_path=None,
        page_count=3,
        figure_count=2,
        skipped_count=1,
        language="Swedish",
        usage=Usage(prompt_tokens=100, completion_tokens=40, total_tokens=140, api_calls=4),
        estimated_cost=estimated_cost,
        currency=currency,
    )


# --- unit: format_convert_result -----------------------------------------


def test_unknown_format_raises_422():
    with pytest.raises(HTTPException) as exc:
        format_convert_result(_result(), "yaml")
    assert exc.value.status_code == 422
    assert "Allowed" in exc.value.detail


@pytest.mark.parametrize("fmt", ["json", "both"])
def test_json_and_both_return_full_model(fmt):
    out = format_convert_result(_result(), fmt)
    assert isinstance(out, ConvertResponse)
    assert out.markdown.startswith("# Title")
    assert out.usage.total_tokens == 140
    assert out.language == "Swedish"


def test_md_returns_markdown_body_with_metadata_headers():
    out = format_convert_result(_result(), "md")
    assert isinstance(out, Response)
    assert out.media_type == "text/markdown; charset=utf-8"
    assert out.body == b"# Title\n\nBody text."
    assert out.headers["X-Figmark-Page-Count"] == "3"
    assert out.headers["X-Figmark-Figure-Count"] == "2"
    assert out.headers["X-Figmark-Language"] == "Swedish"
    assert out.headers["X-Figmark-Total-Tokens"] == "140"
    # No price configured → no cost header (never a misleading 0).
    assert "X-Figmark-Estimated-Cost" not in out.headers


def test_md_includes_cost_header_when_priced():
    out = format_convert_result(_result(estimated_cost=0.0012, currency="EUR"), "md")
    assert out.headers["X-Figmark-Estimated-Cost"]
    assert out.headers["X-Figmark-Currency"] == "EUR"


# --- integration over the wire -------------------------------------------


def _post(client, pdf: bytes, data=None):
    return client.post(
        "/v1/convert",
        headers={"Authorization": f"Bearer {API_TEST_TOKEN}"},
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        data=data or {},
    )


def test_convert_md_format_over_http(make_api_app, tmp_path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = TestClient(make_api_app(FakeClient("En bild på en katt.")))
    resp = _post(client, pdf, data={"format": "md"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "X-Figmark-Page-Count" in resp.headers
    assert resp.text  # raw markdown body, not JSON


def test_convert_default_is_json_over_http(make_api_app, tmp_path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = TestClient(make_api_app(FakeClient("desc")))
    resp = _post(client, pdf)
    assert resp.status_code == 200
    body = resp.json()
    assert "markdown" in body and "usage" in body


def test_convert_unknown_format_is_422_over_http(make_api_app, tmp_path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = TestClient(make_api_app(FakeClient("desc")))
    resp = _post(client, pdf, data={"format": "xml"})
    assert resp.status_code == 422
