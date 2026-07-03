"""LibreChat / Mistral-OCR-compatible surface (T-052).

Drives the same four-call flow LibreChat's default strategy uses — upload → signed
URL → /v1/ocr → delete — against the app with an injected fake client, plus the
auth, signature, and input-validation edge cases.
"""

from __future__ import annotations

import base64

import fitz
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


def _multipage_pdf_bytes(n=3):
    """A text-only n-page PDF with distinct, greppable text per page."""
    doc = fitz.open()
    for i in range(n):
        page = doc.new_page()
        page.insert_text((72, 72), f"Unique text for page number {i}. " * 8)
    data = doc.tobytes()
    doc.close()
    return data


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
    # include_image_base64=false: image entries exist (id + bbox) without data.
    assert payload["pages"][0]["images"]
    assert all(img["image_base64"] is None for img in payload["pages"][0]["images"])
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


def test_unsupported_documented_param_is_422_naming_it(make_api_app, tmp_path):
    """T-057: a documented-but-unsupported Mistral parameter must fail loud."""
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode()
    for param, value in [
        ("table_format", "html"),
        ("extract_header", True),
        ("bbox_annotation_format", {"type": "json_schema"}),
        ("document_annotation_format", {"type": "json_schema"}),
    ]:
        r = client.post(
            "/v1/ocr",
            json={"document": {"type": "document_url", "document_url": data_url}, param: value},
            headers=AUTH,
        )
        assert r.status_code == 422, f"{param}: {r.status_code} {r.text}"
        assert param in r.json()["detail"]
        assert "model, document" in r.json()["detail"]  # names the supported set
        # A null value carries no request, so it passes through.
        ok = client.post(
            "/v1/ocr",
            json={"document": {"type": "document_url", "document_url": data_url}, param: None},
            headers=AUTH,
        )
        assert ok.status_code == 200, f"{param}=null: {ok.status_code} {ok.text}"


def _ocr(client, pdf, **params):
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode()
    return client.post(
        "/v1/ocr",
        json={"document": {"type": "document_url", "document_url": data_url}, **params},
        headers=AUTH,
    )


def test_include_image_base64_returns_inlinable_images(make_api_app, tmp_path):
    """T-058: markdown refs match images[].id, and base64 is the real file bytes."""
    client = _client(make_api_app)
    r = _ocr(client, _pdf_bytes(tmp_path), include_image_base64=True)
    assert r.status_code == 200, r.text
    page = r.json()["pages"][0]
    assert page["images"], "the synthetic PDF's figure should be in images[]"
    img = page["images"][0]
    # Mistral cookbook correlation: the markdown embeds ![id](id).
    assert f"![{img['id']}]({img['id']})" in page["markdown"]
    assert "](images/" not in page["markdown"] and "](diagrams/" not in page["markdown"]
    assert img["image_base64"].startswith("data:image/")
    base64.b64decode(img["image_base64"].split(",", 1)[1], validate=True)
    # bbox in PDF points (the fixture embeds at rect 72,200–172,300).
    assert img["top_left_x"] == 72 and img["bottom_right_y"] == 300
    dims = page["dimensions"]
    assert dims["dpi"] == 72 and dims["width"] > 0 and dims["height"] > 0


def test_image_limit_and_min_size_are_honoured(make_api_app, tmp_path):
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    # limit 0: no images, and the now-unresolvable ref is stripped, not left dead.
    r = _ocr(client, pdf, image_limit=0)
    page = r.json()["pages"][0]
    assert page["images"] == []
    assert "![" not in page["markdown"] and "](images/" not in page["markdown"]
    assert DESC in page["markdown"], "the description caption must survive"
    # min_size larger than the fixture's 100x100 px image: filtered the same way.
    r2 = _ocr(client, pdf, image_min_size=101)
    assert r2.json()["pages"][0]["images"] == []
    # min_size the image satisfies: kept.
    r3 = _ocr(client, pdf, image_min_size=100)
    assert r3.json()["pages"][0]["images"]


def test_cache_hit_still_serves_images(make_api_app, tmp_path):
    """The cached payload carries the figure bytes — a hit is not image-less."""
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    first = _ocr(client, pdf, include_image_base64=True)
    assert first.status_code == 200 and first.headers["X-Figmark-Cache"] == "miss"
    second = _ocr(client, pdf, include_image_base64=True)
    assert second.status_code == 200 and second.headers["X-Figmark-Cache"] == "hit"
    imgs = second.json()["pages"][0]["images"]
    assert imgs and imgs[0]["image_base64"].startswith("data:image/")


def test_image_param_type_validation(make_api_app, tmp_path):
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    assert _ocr(client, pdf, image_limit=-1).status_code == 422
    assert _ocr(client, pdf, image_limit="five").status_code == 422
    assert _ocr(client, pdf, include_image_base64="yes").status_code == 422


def test_unknown_param_is_422(make_api_app, tmp_path):
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode()
    r = client.post(
        "/v1/ocr",
        json={"document": {"type": "document_url", "document_url": data_url}, "frobnicate": 1},
        headers=AUTH,
    )
    assert r.status_code == 422 and "frobnicate" in r.json()["detail"]


def test_file_id_document_reference_roundtrips(make_api_app, tmp_path):
    """T-059: document {type: 'file', file_id} resolves against /v1/files directly."""
    client = _client(make_api_app)
    pdf = _pdf_bytes(tmp_path)
    file_id = client.post(
        "/v1/files", files={"file": ("doc.pdf", pdf, "application/pdf")}, headers=AUTH
    ).json()["id"]
    r = client.post(
        "/v1/ocr",
        json={"document": {"type": "file", "file_id": file_id}},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    assert DESC in r.json()["pages"][0]["markdown"]
    # Unknown id: clean 404. Missing id: 422.
    unknown = client.post(
        "/v1/ocr", json={"document": {"type": "file", "file_id": "0" * 32}}, headers=AUTH
    )
    assert unknown.status_code == 404
    missing = client.post("/v1/ocr", json={"document": {"type": "file"}}, headers=AUTH)
    assert missing.status_code == 422


def test_pages_selection_returns_exactly_requested(make_api_app):
    """T-059: pages=[0, 2] → those pages only, original 0-based indices kept."""
    client = _client(make_api_app)
    r = _ocr(client, _multipage_pdf_bytes(3), pages=[0, 2])
    assert r.status_code == 200, r.text
    pages = r.json()["pages"]
    assert [p["index"] for p in pages] == [0, 2]
    assert "page number 0" in pages[0]["markdown"]
    assert "page number 2" in pages[1]["markdown"]
    assert all("page number 1" not in p["markdown"] for p in pages)
    assert r.json()["usage_info"]["pages_processed"] == 2


def test_pages_range_string_form(make_api_app):
    client = _client(make_api_app)
    r = _ocr(client, _multipage_pdf_bytes(4), pages=["1-2"])
    assert r.status_code == 200, r.text
    assert [p["index"] for p in r.json()["pages"]] == [1, 2]


def test_pages_out_of_range_is_422(make_api_app):
    client = _client(make_api_app)
    r = _ocr(client, _multipage_pdf_bytes(2), pages=[0, 5])
    assert r.status_code == 422 and "out of range" in r.json()["detail"]
    # Malformed forms fail loud too.
    assert _ocr(client, _multipage_pdf_bytes(2), pages=[]).status_code == 422
    assert _ocr(client, _multipage_pdf_bytes(2), pages=[-1]).status_code == 422
    assert _ocr(client, _multipage_pdf_bytes(2), pages=["2-1"]).status_code == 422


def test_pages_served_from_full_document_cache(make_api_app):
    """A full-document cache entry answers a pages subset without a pipeline run."""
    client = _client(make_api_app)
    pdf = _multipage_pdf_bytes(3)
    full = _ocr(client, pdf)
    assert full.status_code == 200 and full.headers["X-Figmark-Cache"] == "miss"
    subset = _ocr(client, pdf, pages=[2])
    assert subset.status_code == 200 and subset.headers["X-Figmark-Cache"] == "hit"
    (page,) = subset.json()["pages"]
    assert page["index"] == 2 and "page number 2" in page["markdown"]
    # Out-of-range is still a 422 on the cached path, not a silent shrink.
    assert _ocr(client, pdf, pages=[7]).status_code == 422


def test_pages_sliced_run_is_cached_under_its_selection(make_api_app):
    client = _client(make_api_app)
    pdf = _multipage_pdf_bytes(3)
    first = _ocr(client, pdf, pages=[1])
    assert first.status_code == 200 and first.headers["X-Figmark-Cache"] == "miss"
    again = _ocr(client, pdf, pages=[1])
    assert again.status_code == 200 and again.headers["X-Figmark-Cache"] == "hit"
    assert [p["index"] for p in again.json()["pages"]] == [1]
    assert "page number 1" in again.json()["pages"][0]["markdown"]


def test_split_pages_uses_page_markers():
    md = "<!-- page 1 -->\nHello\n\n<!-- page 2 -->\nWorld\n"
    pages = split_pages(md)
    assert [p["index"] for p in pages] == [0, 1]
    assert pages[0]["markdown"] == "Hello"
    assert pages[1]["markdown"] == "World"
    # No marker → single page with the whole body.
    assert split_pages("just text")[0]["markdown"] == "just text"
