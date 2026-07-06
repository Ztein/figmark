"""T-060: the document-level cache on the HTTP surface.

A second upload of an identical document must be served from the cache — no
pipeline run, no vision-model calls — and be labelled as a hit. Config changes
miss (T-034 parity). Management endpoints delete one document or clear all,
behind the same bearer auth as conversion.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
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


# --- T-062: optional cache admin token ---------------------------------------


def test_admin_token_separates_cache_management(make_api_app):
    """With FIGMARK_CACHE_ADMIN_TOKEN set: the conversion token gets a clear
    403 on management (not a silent pass), the admin token works, and the
    admin token does NOT convert."""
    from fastapi.testclient import TestClient

    from .conftest import API_TEST_TOKEN
    from .fakes import FakeClient

    http = TestClient(make_api_app(FakeClient("x"), cache_admin_token="admin-secret"))
    convert_auth = {"Authorization": f"Bearer {API_TEST_TOKEN}"}
    admin_auth = {"Authorization": "Bearer admin-secret"}

    assert http.get("/v1/cache/stats", headers=convert_auth).status_code == 403
    assert http.delete("/v1/cache", headers=convert_auth).status_code == 403
    assert http.delete("/v1/cache/" + "0" * 64, headers=convert_auth).status_code == 403

    assert http.get("/v1/cache/stats", headers=admin_auth).status_code == 200
    assert http.delete("/v1/cache", headers=admin_auth).status_code == 200

    # The admin token is management-only: it cannot convert.
    r = http.post(
        "/v1/convert", headers=admin_auth, files={"file": ("d.pdf", b"x", "application/pdf")}
    )
    assert r.status_code == 401

    # Garbage token: 401 either way.
    assert http.get("/v1/cache/stats", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_without_admin_token_conversion_token_manages(make_api_app):
    """Default single-token model unchanged: no admin token configured →
    the conversion token manages the cache."""
    from fastapi.testclient import TestClient

    from .conftest import API_TEST_TOKEN
    from .fakes import FakeClient

    http = TestClient(make_api_app(FakeClient("x")))
    auth = {"Authorization": f"Bearer {API_TEST_TOKEN}"}
    assert http.get("/v1/cache/stats", headers=auth).status_code == 200
    assert http.delete("/v1/cache", headers=auth).status_code == 200


def test_conversion_survives_a_broken_cache_backend(make_api_app, tmp_path: Path, caplog):
    """T-072: the cache is an accelerator, not a point of failure. With the
    cache database corrupted under a running app, a conversion must still
    return 200 (get degrades to a miss, the post-conversion put is dropped) —
    loudly, in the logs, but never as the client's problem."""
    import logging

    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    app = make_api_app(FakeClient("En bild på en katt."))
    store = app.state.cache_store
    assert store is not None
    store.db_path.write_bytes(b"this is not a sqlite database " * 64)
    for suffix in ("-wal", "-shm"):
        store.db_path.with_name(store.db_path.name + suffix).unlink(missing_ok=True)

    with caplog.at_level(logging.ERROR, logger="figmark.cache"):
        r = _post(TestClient(app), pdf)
    assert r.status_code == 200, r.text
    assert "En bild på en katt." in r.json()["markdown"]
    assert r.headers["x-figmark-cache"] == "miss"
    assert "cache" in caplog.text and "failed" in caplog.text, "degraded loudly, not silently"


# --- T-073: single-flight — concurrent identical uploads run one conversion --


class _SlowFakeClient(FakeClient):
    """FakeClient whose figure-description call is slow, so overlapping
    requests reliably find the first conversion still in flight."""

    def __init__(self, image_reply: str, delay_seconds: float):
        super().__init__(image_reply)
        self._delay = delay_seconds

    def _create(self, model, max_tokens, messages, **kwargs):
        content = messages[0]["content"]
        if not isinstance(content, str):  # a describe call carries an image
            import time

            time.sleep(self._delay)
        return super()._create(model, max_tokens, messages, **kwargs)


@contextmanager
def _running(app):
    """Serve the app under real uvicorn in a thread and yield its base URL.

    Coalescing happens BETWEEN concurrent requests on one event loop —
    TestClient can't exercise that (it builds a fresh portal/loop per
    request), so these tests go over real HTTP, like conftest's
    mock_llm_server."""
    import socket
    import threading
    import time

    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "test app did not start"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _http_post(base: str, pdf: bytes):
    import httpx

    return httpx.post(
        f"{base}/v1/convert",
        headers=AUTH,
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        timeout=60,
    )


def _concurrent_posts(base: str, bodies: list[bytes]):
    import threading

    results: list = [None] * len(bodies)

    def post(i: int) -> None:
        results[i] = _http_post(base, bodies[i])

    threads = [threading.Thread(target=post, args=(i,)) for i in range(len(bodies))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_identical_uploads_run_one_conversion(make_api_app, tmp_path: Path):
    """T-073: N simultaneous uploads of one document must cost ONE pipeline
    run — the followers coalesce onto the leader's in-flight conversion and
    return the same result, labelled as served from cache."""
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    fake = _SlowFakeClient("En bild på en katt.", delay_seconds=2.0)
    app = make_api_app(fake, max_concurrent_jobs=4)

    with _running(app) as base:
        results = _concurrent_posts(base, [pdf] * 3)

    assert [r.status_code for r in results] == [200, 200, 200]
    assert len(fake.describe_prompts) == 1, "one conversion's worth of upstream calls"
    headers = sorted(r.headers["x-figmark-cache"] for r in results)
    assert headers == ["coalesced", "coalesced", "miss"]
    markdowns = {r.json()["markdown"] for r in results}
    assert len(markdowns) == 1, "followers get the leader's result"
    assert all(r.json()["cached"] for r in results if r.headers["x-figmark-cache"] == "coalesced")


def test_coalesced_follower_receives_the_leaders_error(make_api_app, tmp_path: Path):
    """A failed leader must not poison or hang followers: they receive the
    leader's error, and a failure is never cached or sticky."""
    import time

    class _SlowThenFailingClient:
        """Language call succeeds; the describe call is slow (so a follower
        reliably coalesces) and then returns an empty completion — the hard,
        deliberately-not-retried T-033 error."""

        def __init__(self):
            from types import SimpleNamespace

            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, model, max_tokens, messages, **kwargs):
            from .fakes import make_response

            content = messages[0]["content"]
            if isinstance(content, str):
                return make_response("Swedish")
            time.sleep(2.0)
            return make_response("")  # empty completion → hard error, no retry

    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    app = make_api_app(_SlowThenFailingClient(), max_concurrent_jobs=4)

    with _running(app) as base:
        results = _concurrent_posts(base, [pdf] * 2)
        # Leader and follower fail identically — the follower is not hung,
        # not silently served a partial result.
        statuses = sorted(r.status_code for r in results)
        assert statuses == [500, 500], [r.text for r in results]
        # The failure is not sticky: a fresh upload leads again (and fails
        # again, honestly) instead of being served a cached error.
        r = _http_post(base, pdf)
        assert r.status_code == 500


def test_different_documents_do_not_coalesce(make_api_app, tmp_path: Path):
    """Coalescing keys on the document digest: two different documents
    uploaded simultaneously both convert."""
    pdf_a = synthetic_pdf(tmp_path / "a.pdf").read_bytes()
    pdf_b = synthetic_pdf(tmp_path / "b.pdf").read_bytes() + b"\n%tail"  # distinct digest
    fake = _SlowFakeClient("En bild på en katt.", delay_seconds=1.0)
    app = make_api_app(fake, max_concurrent_jobs=4)

    with _running(app) as base:
        results = _concurrent_posts(base, [pdf_a, pdf_b])

    assert [r.status_code for r in results] == [200, 200]
    assert {r.headers["x-figmark-cache"] for r in results} == {"miss"}, "no false coalescing"
