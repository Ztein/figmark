"""T-061: figure descriptions shared across requests and documents.

The same image content (digest) must be described once — whatever document,
page, or request it arrives in. Diagram regions participate via the digest of
their rendered pixels. Entries belong to the document that first created them,
so purging a document also purges the descriptions it introduced.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from figmark.cache import CacheStore, SharedDescriptionCache
from figmark.config import load_config
from figmark.pipeline import convert

from .fakes import FakeClient


def _pdf_with_image(path: Path, text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text * 15)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 120))
    pix.set_rect(pix.irect, (60, 90, 210))
    page.insert_image(fitz.Rect(72, 300, 192, 420), pixmap=pix)
    doc.save(path)
    doc.close()
    return path


def _pdf_with_diagram(path: Path, text: str) -> Path:
    """A bar-chart-like drawing cluster that detection accepts as a diagram
    (an irregular histogram — a regular grid is filtered as table-like)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 40), text * 10)
    heights = [30 + ((i * 37) % 90) for i in range(14)]
    for i, h in enumerate(heights):
        x = 100 + i * 18
        page.draw_rect(fitz.Rect(x, 420 - h, x + 12, 420), color=(0, 0, 1), fill=(0, 0, 1))
    for j in range(10):
        y = 320 + j * 10
        page.draw_rect(fitz.Rect(95, y, 360, y + 2.2), color=(0.5, 0.5, 0.5))
    for k in range(8):
        page.draw_rect(fitz.Rect(92 + k * 33, 421, 94 + k * 33, 426), color=(0, 0, 0))
    doc.save(path)
    doc.close()
    return path


def _shared(tmp_path: Path, doc_digest: str = "doc-under-test") -> SharedDescriptionCache:
    store = CacheStore(tmp_path / "shared-cache", max_bytes=10_000_000, max_age_hours=24)
    return SharedDescriptionCache(store, doc_digest)


def test_same_image_in_two_documents_is_described_once(
    env_with_key, project_root: Path, tmp_path: Path
):
    cfg = load_config(project_root / "config.example.yaml")
    shared = _shared(tmp_path)

    a = _pdf_with_image(tmp_path / "a.pdf", "Report about apples. ")
    b = _pdf_with_image(tmp_path / "b.pdf", "Totally different bananas. ")

    client_a = FakeClient("En delad bild.")
    convert(a, cfg, tmp_path / "out-a", client=client_a, quiet=True, shared_cache=shared)
    assert len(client_a.describe_prompts) == 1

    client_b = FakeClient("SHOULD NOT BE CALLED")
    result_b = convert(b, cfg, tmp_path / "out-b", client=client_b, quiet=True, shared_cache=shared)
    assert client_b.describe_prompts == [], "the shared cache must serve the image"
    assert "En delad bild." in result_b.markdown, "document B reuses A's description"


def test_same_diagram_in_two_documents_is_described_once(
    env_with_key, project_root: Path, tmp_path: Path
):
    cfg = load_config(project_root / "config.example.yaml")
    shared = _shared(tmp_path)

    a = _pdf_with_diagram(tmp_path / "a.pdf", "Quarterly chart report. ")
    b = _pdf_with_diagram(tmp_path / "b.pdf", "Another appendix entirely. ")

    client_a = FakeClient("Ett delat diagram.")
    result_a = convert(a, cfg, tmp_path / "out-a", client=client_a, quiet=True, shared_cache=shared)
    assert result_a.figure_count >= 1, "precondition: the synthetic cluster is a diagram"
    diagram_calls = len(client_a.describe_prompts)
    assert diagram_calls >= 1

    client_b = FakeClient("SHOULD NOT BE CALLED")
    result_b = convert(b, cfg, tmp_path / "out-b", client=client_b, quiet=True, shared_cache=shared)
    assert client_b.describe_prompts == []
    assert "Ett delat diagram." in result_b.markdown


def test_skip_markers_are_cached_too(env_with_key, project_root: Path, tmp_path: Path):
    """A [SKIP] (decorative logo) verdict is a result — reusing it saves the call."""
    cfg = load_config(project_root / "config.example.yaml")
    shared = _shared(tmp_path)

    a = _pdf_with_image(tmp_path / "a.pdf", "Doc with a logo. ")
    b = _pdf_with_image(tmp_path / "b.pdf", "Other doc, same logo. ")

    convert(
        a, cfg, tmp_path / "out-a", client=FakeClient("[SKIP]"), quiet=True, shared_cache=shared
    )
    client_b = FakeClient("SHOULD NOT BE CALLED")
    result_b = convert(b, cfg, tmp_path / "out-b", client=client_b, quiet=True, shared_cache=shared)
    assert client_b.describe_prompts == []
    assert result_b.skipped_count == 1, "the cached skip verdict applies in document B"


def test_purging_the_originating_document_purges_its_descriptions(tmp_path: Path):
    store = CacheStore(tmp_path / "c", max_bytes=10_000_000, max_age_hours=24)
    shared = SharedDescriptionCache(store, "digest-of-doc-a")
    shared.put("img-abc-fp", "En bild.")
    assert SharedDescriptionCache(store, "other").get("img-abc-fp") == "En bild."

    store.delete_document("digest-of-doc-a")
    assert shared.get("img-abc-fp") is None, (
        "deleting a document removes the descriptions it introduced"
    )


def test_api_shares_descriptions_across_different_documents(make_api_app, tmp_path: Path):
    """End-to-end over HTTP: two different documents, one shared image → the
    second upload is a document-cache MISS but makes no describe calls."""
    from fastapi.testclient import TestClient

    from .conftest import API_TEST_TOKEN

    a = _pdf_with_image(tmp_path / "a.pdf", "Alpha document. ").read_bytes()
    b = _pdf_with_image(tmp_path / "b.pdf", "Beta document, different text. ").read_bytes()

    client = FakeClient("En delad bild.")
    http = TestClient(make_api_app(client))
    auth = {"Authorization": f"Bearer {API_TEST_TOKEN}"}

    r1 = http.post("/v1/convert", headers=auth, files={"file": ("a.pdf", a, "application/pdf")})
    assert r1.status_code == 200
    calls = len(client.describe_prompts)
    assert calls == 1

    r2 = http.post("/v1/convert", headers=auth, files={"file": ("b.pdf", b, "application/pdf")})
    assert r2.status_code == 200
    assert r2.headers.get("x-figmark-cache") == "miss", "different document → doc-level miss"
    assert len(client.describe_prompts) == calls, "…but the image description is reused"
    assert "En delad bild." in r2.json()["markdown"]
