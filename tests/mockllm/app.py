"""A tiny OpenAI-compatible mock server for offline / air-gapped testing.

Serves ``POST /v1/chat/completions`` with the OpenAI envelope, branching the same
way the real figmark calls do (text-only call containing "Identify the language"
→ a language name; another text-only call → a document summary; a call carrying an
image → a figure description). It returns canned text so the whole pipeline and
the container stack can be exercised with no real model and no internet.

Used two ways:
  * a pytest fixture points a real figmark OpenAI client at it (HTTP end-to-end);
  * a docker-compose ``mock-llm`` service stands in for the vision endpoint.

Replies are configurable via env: ``MOCK_LANGUAGE`` (default "Swedish"),
``MOCK_SUMMARY``, ``MOCK_IMAGE_REPLY``, and ``MOCK_SKIP=1`` to return "[SKIP]".
This app is test/dev only — it never ships in the production image.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request

app = FastAPI(title="figmark-mock-llm")


def _language() -> str:
    return os.environ.get("MOCK_LANGUAGE", "Swedish")


def _summary() -> str:
    return os.environ.get("MOCK_SUMMARY", "Detta är ett testdokument om katter.")


def _image_reply() -> str:
    if os.environ.get("MOCK_SKIP") == "1":
        return "[SKIP]"
    return os.environ.get("MOCK_IMAGE_REPLY", "En bild på en katt.")


def _reply_for(messages: list) -> str:
    content = messages[0].get("content")
    if isinstance(content, str):
        if "Identify the language" in content:
            return _language()
        return _summary()
    # content is a list with an image part → a figure description
    return _image_reply()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict:
    body = await request.json()
    text = _reply_for(body.get("messages", [{}]))
    return {
        "id": "mock-completion",
        "object": "chat.completion",
        "created": 0,
        "model": body.get("model", "mock"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
