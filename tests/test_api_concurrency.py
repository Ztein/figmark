"""Phase 2: the concurrency gate returns 429 when all conversion slots are busy."""

from __future__ import annotations

import asyncio
import threading

import httpx

from .conftest import API_TEST_TOKEN
from .fakes import FakeClient, synthetic_pdf

AUTH = {"Authorization": f"Bearer {API_TEST_TOKEN}"}


class BlockingFakeClient(FakeClient):
    """Blocks on the first image-description call until released."""

    def __init__(self, image_reply: str, gate: threading.Event):
        super().__init__(image_reply)
        self._gate = gate

    def _create(self, model, max_tokens, messages, **kwargs):
        content = messages[0]["content"]
        if not isinstance(content, str):  # an image description call
            self._gate.wait(timeout=5)
        return super()._create(model, max_tokens, messages, **kwargs)


def test_second_concurrent_request_gets_429(make_api_app, tmp_path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf").read_bytes()
    gate = threading.Event()
    app = make_api_app(BlockingFakeClient("desc", gate), max_concurrent_jobs=1)

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            files = {"file": ("doc.pdf", pdf, "application/pdf")}
            first = asyncio.create_task(ac.post("/v1/convert", files=files, headers=AUTH))
            await asyncio.sleep(0.4)  # let the first request enter convert and hold the slot
            second = await ac.post(
                "/v1/convert",
                files={"file": ("d2.pdf", pdf, "application/pdf")},
                headers=AUTH,
            )
            gate.set()
            first_resp = await first
            return first_resp, second

    first_resp, second = asyncio.run(go())
    assert second.status_code == 429
    assert first_resp.status_code == 200
