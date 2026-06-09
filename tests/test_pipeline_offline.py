"""Offline end-to-end pipeline test with a fake vision client.

Drives the real `main.run` against a synthetic one-page PDF (text + one embedded
image) but swaps the OpenAI client for a fake that records the prompts it is sent.
This verifies the new wiring without any API traffic:

  - the document summary is computed and written to disk,
  - that summary is injected into the figure description prompt,
  - a "[SKIP]" reply removes the (decorative) image from the Markdown.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from figmark import main as main_module

SUMMARY_REPLY = "Detta är ett testdokument om katter."


def _make_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


DETECTED_LANGUAGE = "Swedish"


class FakeClient:
    """Records prompts and returns canned text. Text-only calls are either the
    language-detection call or the summary call; calls carrying an image are a
    figure description."""

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
                return _make_response(DETECTED_LANGUAGE)
            self.summary_prompts.append(content)
            return _make_response(SUMMARY_REPLY)
        text = next(part["text"] for part in content if part["type"] == "text")
        self.describe_prompts.append(text)
        return _make_response(self.image_reply)


def _synthetic_pdf(path: Path) -> Path:
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


@pytest.fixture
def fake_client(monkeypatch):
    holder = {}

    def install(image_reply: str) -> FakeClient:
        client = FakeClient(image_reply)
        monkeypatch.setattr(main_module, "make_client", lambda cfg: client)
        holder["client"] = client
        return client

    return install


def test_summary_is_computed_and_injected_into_figure_prompt(
    env_with_key, fake_client, project_root: Path, tmp_path: Path
):
    pdf = _synthetic_pdf(tmp_path / "doc.pdf")
    client = fake_client("En bild på en katt.")

    exit_code = main_module.run(pdf, project_root / "config.yaml", tmp_path / "output")
    assert exit_code == 0

    # The language was detected once and cached.
    assert len(client.language_prompts) == 1
    lang_file = tmp_path / "output" / "doc" / "document_language.txt"
    assert lang_file.read_text(encoding="utf-8").strip() == DETECTED_LANGUAGE

    # The summary was generated once and cached to disk.
    summary_file = tmp_path / "output" / "doc" / "document_summary.txt"
    assert summary_file.read_text(encoding="utf-8").strip() == SUMMARY_REPLY
    assert len(client.summary_prompts) == 1

    # The figure prompt carries the document summary AND the resolved language.
    assert client.describe_prompts, "the image should have been described"
    assert "[Document type]" in client.describe_prompts[0]
    assert SUMMARY_REPLY in client.describe_prompts[0]
    assert f"Write your answer in {DETECTED_LANGUAGE}." in client.describe_prompts[0]

    # The description is inlined in the Markdown.
    md = (tmp_path / "output" / "doc" / "doc.md").read_text(encoding="utf-8")
    assert "En bild på en katt." in md
    assert "](images/" in md


def test_skip_reply_drops_image_from_markdown(
    env_with_key, fake_client, project_root: Path, tmp_path: Path
):
    pdf = _synthetic_pdf(tmp_path / "doc.pdf")
    fake_client("[SKIP]")

    exit_code = main_module.run(pdf, project_root / "config.yaml", tmp_path / "output")
    assert exit_code == 0

    md = (tmp_path / "output" / "doc" / "doc.md").read_text(encoding="utf-8")
    assert "Intro text about cats." in md
    assert "](images/" not in md, "a skip-marked decorative image must not be embedded"
