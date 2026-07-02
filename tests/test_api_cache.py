"""T-060: the document-level cache on the HTTP surface.

A second upload of an identical document must be served from the cache — no
pipeline run, no vision-model calls — and be labelled as a hit. Config changes
miss (T-034 parity). Management endpoints delete one document or clear all,
behind the same bearer auth as conversion.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from .conftest import API_TEST_TOKEN
from .fakes import FakeClient, synthetic_pdf

AUTH = {"Authorization": f"Bearer {API_TEST_TOKEN}"}


def _post(client: TestClient, pdf: bytes):
    return client.post(
        "/v1/convert", headers=AUTH, files={"file": ("doc.pdf", pdf, "application/pdf")}
    )


def test_second_identical_upload_is_a_cache_hit(make_api_app, tmp_path: Path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()

    first_client = FakeClient("En bild på en katt.")
    app = make_api_app(first_client)
    http = TestClient(app)

    r1 = _post(http, pdf)
    assert r1.status_code == 200
    assert r1.headers.get("x-figmark-cache") == "miss"
    assert r1.json()["cached"] is False
    calls_after_first = len(first_client.describe_prompts)
    assert calls_after_first >= 1

    r2 = _post(http, pdf)
    assert r2.status_code == 200
    assert r2.headers.get("x-figmark-cache") == "hit"
    body = r2.json()
    assert body["cached"] is True
    assert body["markdown"] == r1.json()["markdown"]
    assert len(first_client.describe_prompts) == calls_after_first, (
        "a cache hit must make no new model calls"
    )


def test_cache_hit_carries_original_usage_labelled(make_api_app, tmp_path: Path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    http = TestClient(make_api_app(FakeClient("En bild.")))
    r1 = _post(http, pdf)
    r2 = _post(http, pdf)
    # The original run's usage is echoed for information, but the response says
    # it is cached — no pretending it was fresh spend.
    assert r2.json()["usage"] == r1.json()["usage"]
    assert r2.json()["cached"] is True


def test_ocr_surface_shares_the_cache(make_api_app, tmp_path: Path):
    import base64

    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = FakeClient("En bild.")
    http = TestClient(make_api_app(client))

    data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode()
    body = {"document": {"type": "document_url", "document_url": data_url}}

    r1 = http.post("/v1/ocr", headers=AUTH, json=body)
    assert r1.status_code == 200
    calls = len(client.describe_prompts)

    r2 = http.post("/v1/ocr", headers=AUTH, json=body)
    assert r2.status_code == 200
    assert r2.headers.get("x-figmark-cache") == "hit"
    assert len(client.describe_prompts) == calls, "OCR hit must not re-describe"
    assert r2.json()["pages"] == r1.json()["pages"]


def test_convert_result_is_reused_by_ocr_and_vice_versa(make_api_app, tmp_path: Path):
    """Same document, either surface: one pipeline run total."""
    import base64

    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = FakeClient("En bild.")
    http = TestClient(make_api_app(client))

    assert _post(http, pdf).status_code == 200
    calls = len(client.describe_prompts)
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode()
    r = http.post(
        "/v1/ocr",
        headers=AUTH,
        json={"document": {"type": "document_url", "document_url": data_url}},
    )
    assert r.status_code == 200
    assert r.headers.get("x-figmark-cache") == "hit"
    assert len(client.describe_prompts) == calls


def test_different_document_misses(make_api_app, tmp_path: Path):
    pdf_a = synthetic_pdf(tmp_path / "a.pdf").read_bytes()
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Completely different text. " * 20)
    doc.save(tmp_path / "b.pdf")
    doc.close()
    pdf_b = (tmp_path / "b.pdf").read_bytes()

    http = TestClient(make_api_app(FakeClient("En bild.")))
    assert _post(http, pdf_a).headers.get("x-figmark-cache") == "miss"
    assert _post(http, pdf_b).headers.get("x-figmark-cache") == "miss"


def test_delete_single_document_from_cache(make_api_app, tmp_path: Path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    client = FakeClient("En bild.")
    http = TestClient(make_api_app(client))
    _post(http, pdf)
    digest = hashlib.sha256(pdf).hexdigest()

    r = http.delete(f"/v1/cache/{digest}", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["deleted"] >= 1

    r2 = _post(http, pdf)
    assert r2.headers.get("x-figmark-cache") == "miss", "deleted → converted afresh"


def test_clear_whole_cache(make_api_app, tmp_path: Path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    http = TestClient(make_api_app(FakeClient("En bild.")))
    _post(http, pdf)

    r = http.delete("/v1/cache", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["deleted"] >= 1
    assert _post(http, pdf).headers.get("x-figmark-cache") == "miss"


def test_cache_stats_endpoint(make_api_app, tmp_path: Path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    http = TestClient(make_api_app(FakeClient("En bild.")))
    _post(http, pdf)
    r = http.get("/v1/cache/stats", headers=AUTH)
    assert r.status_code == 200
    s = r.json()
    assert s["entries"] >= 1 and s["total_bytes"] > 0


def test_cache_endpoints_require_auth(make_api_app):
    http = TestClient(make_api_app(FakeClient("x")))
    assert http.get("/v1/cache/stats").status_code in (401, 403)
    assert http.delete("/v1/cache").status_code in (401, 403)
    assert http.delete(f"/v1/cache/{'0' * 64}").status_code in (401, 403)


def test_disabled_cache_never_hits_and_stats_404(make_api_app, tmp_path: Path, project_root):
    import yaml

    from figmark.config import load_config

    raw = yaml.safe_load((project_root / "config.example.yaml").read_text(encoding="utf-8"))
    raw["cache"] = {"enabled": False}
    cfg_path = tmp_path / "nocache.yaml"
    cfg_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = load_config(cfg_path)

    from figmark.api import ServerSettings, create_app

    settings = ServerSettings(
        auth_token=API_TEST_TOKEN,
        config_path=cfg_path,
        max_upload_bytes=50 * 1024 * 1024,
        work_dir=tmp_path / "work",
        request_timeout_seconds=30.0,
        max_concurrent_jobs=2,
    )
    client = FakeClient("En bild.")
    http = TestClient(create_app(settings=settings, cfg=cfg, client=client))

    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    r1 = _post(http, pdf)
    r2 = _post(http, pdf)
    assert r1.status_code == r2.status_code == 200
    assert r2.headers.get("x-figmark-cache") in (None, "off"), "disabled → never a hit"
    assert http.get("/v1/cache/stats", headers=AUTH).status_code == 404
