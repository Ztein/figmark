"""Phase 3: the mock OpenAI-compatible server returns OpenAI-shaped, branched replies."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .mockllm.app import app

client = TestClient(app)


def _content(messages):
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": messages})
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    return body["choices"][0]["message"]["content"]


def test_language_detection_branch():
    assert _content([{"role": "user", "content": "Identify the language of: hello"}]) == "Swedish"


def test_summary_branch():
    out = _content([{"role": "user", "content": "Summarise this document please"}])
    assert "testdokument" in out


def test_image_description_branch():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
            ],
        }
    ]
    assert _content(messages) == "En bild på en katt."


def test_healthz():
    assert client.get("/healthz").json()["status"] == "ok"
