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

import pytest

from figmark import main as main_module

from .fakes import DETECTED_LANGUAGE, SUMMARY_REPLY, FakeClient
from .fakes import synthetic_pdf as _synthetic_pdf


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

    exit_code = main_module.run(pdf, project_root / "config.example.yaml", tmp_path / "output")
    assert exit_code == 0

    # The language was detected once and cached (fingerprinted filename, T-067).
    assert len(client.language_prompts) == 1
    lang_file = next((tmp_path / "output" / "doc").glob("document_language-*.txt"))
    assert lang_file.read_text(encoding="utf-8").strip() == DETECTED_LANGUAGE

    # The summary was generated once and cached to disk.
    summary_file = next((tmp_path / "output" / "doc").glob("document_summary-*.txt"))
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

    exit_code = main_module.run(pdf, project_root / "config.example.yaml", tmp_path / "output")
    assert exit_code == 0

    md = (tmp_path / "output" / "doc" / "doc.md").read_text(encoding="utf-8")
    assert "Intro text about cats." in md
    assert "](images/" not in md, "a skip-marked decorative image must not be embedded"
