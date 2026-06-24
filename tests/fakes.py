"""Shared offline test doubles.

A fake OpenAI client and a synthetic PDF builder, used by the offline pipeline and
API tests so the whole flow runs with no network and no real model. The fake
mirrors how the real ``OpenAI`` client is called in ``figmark`` (text-only calls
are language detection or the document summary; calls carrying an image are a
figure description).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz

SUMMARY_REPLY = "Detta är ett testdokument om katter."
DETECTED_LANGUAGE = "Swedish"


def make_response(
    text: str,
    *,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    finish_reason: str = "stop",
):
    """Build an object shaped like an OpenAI chat completion response.

    Includes a ``usage`` block and a ``finish_reason`` like the real API, so usage
    accounting and truncation detection can be exercised offline.
    """
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


class FakeClient:
    """Records prompts and returns canned text.

    Text-only calls are either the language-detection call or the summary call;
    calls carrying an image are a figure description. ``image_reply`` is what every
    figure description returns (pass ``"[SKIP]"`` to exercise the significance gate).
    """

    def __init__(self, image_reply: str):
        self.image_reply = image_reply
        self.describe_prompts: list[str] = []
        self.summary_prompts: list[str] = []
        self.language_prompts: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, max_tokens, messages, **kwargs):
        content = messages[0]["content"]
        if isinstance(content, str):
            if "Identify the language" in content:
                self.language_prompts.append(content)
                return make_response(DETECTED_LANGUAGE)
            self.summary_prompts.append(content)
            return make_response(SUMMARY_REPLY)
        text = next(part["text"] for part in content if part["type"] == "text")
        self.describe_prompts.append(text)
        return make_response(self.image_reply)


def synthetic_pdf(path: Path) -> Path:
    """Write a one-page PDF: text, one embedded 100x100 image, more text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Intro text about cats. " * 12)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
    pix.set_rect(pix.irect, (120, 160, 200))
    page.insert_image(fitz.Rect(72, 200, 172, 300), pixmap=pix)
    page.insert_text((72, 360), "More text after the image. " * 12)
    doc.save(path)
    doc.close()
    return path
