"""The description cache: same image + same request → same text, no second call."""

import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from figmark import cache as c


def _img(color):
    return Image.new("RGB", (8, 8), color)


def test_key_depends_on_pixels_prompt_and_params():
    k = c.DescriptionCache.key
    base = k(_img("red"), "p", {"model": "m"})
    assert base == k(_img("red"), "p", {"model": "m"})
    assert base != k(_img("blue"), "p", {"model": "m"})
    assert base != k(_img("red"), "q", {"model": "m"})
    assert base != k(_img("red"), "p", {"model": "n"})


def test_empty_answers_are_not_stored(tmp_path):
    dc = c.DescriptionCache(tmp_path / "d.sqlite")
    assert dc.get("k") is None
    dc.put("k", "  ", "m")
    assert dc.get("k") is None


def test_identical_images_in_flight_are_described_once(tmp_path, monkeypatch):
    from docling.models.stages.picture_description import picture_description_api_model as m

    calls, lock = [], threading.Lock()

    def fake(image, prompt, url, timeout=20, headers=None, **params):
        with lock:
            calls.append(1)
        threading.Event().wait(0.05)
        from docling.datamodel.base_models import ApiImageRequestResult, VlmStopReason

        return ApiImageRequestResult(text="a red square", num_tokens=3, stop_reason=VlmStopReason.END_OF_SEQUENCE)

    monkeypatch.setattr(m, "api_image_request", fake)
    dc = c.DescriptionCache(tmp_path / "d.sqlite")
    c.install(dc)
    with ThreadPoolExecutor(8) as pool:
        texts = list(pool.map(lambda _: m.api_image_request(_img("red"), "p", "u", model="x").text, range(8)))
    assert texts == ["a red square"] * 8
    assert len(calls) == 1
    assert (dc.hits, dc.misses) == (7, 1)


def test_a_failed_call_releases_waiters(tmp_path, monkeypatch):
    from docling.models.stages.picture_description import picture_description_api_model as m

    def boom(*a, **k):
        raise RuntimeError("endpoint down")

    monkeypatch.setattr(m, "api_image_request", boom)
    dc = c.DescriptionCache(tmp_path / "d.sqlite")
    c.install(dc)
    for _ in range(2):  # the second call must not hang on the first one's key
        try:
            m.api_image_request(_img("red"), "p", "u", model="x")
        except RuntimeError:
            pass
    assert dc.misses == 2
