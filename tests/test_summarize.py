"""Unit tests for document-summary sample collection and the T-067 loud floor
on the language/summary model calls (offline, no API)."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from figmark.output import PageData
from figmark.pdf_loader import ImageBlock, TextBlock
from figmark.summarize import collect_sample_text, detect_language, summarize_document

from .fakes import make_response


def _text_page(page_num: int, text: str) -> PageData:
    page = PageData(page_num=page_num, is_ocr=False)
    page.blocks = [TextBlock(bbox=(0, 0, 100, 20), text=text)]
    return page


def test_collect_sample_text_caps_at_max_words():
    pages = [_text_page(1, "one two three four five"), _text_page(2, "six seven eight")]
    assert collect_sample_text(pages, max_words=4) == "one two three four"


def test_collect_sample_text_spans_pages_until_quota():
    pages = [_text_page(1, "a b"), _text_page(2, "c d e")]
    assert collect_sample_text(pages, max_words=4) == "a b c d"


def test_collect_sample_text_reads_ocr_pages():
    page = PageData(page_num=1, is_ocr=True)
    page.ocr_text = "scanned words here"
    assert collect_sample_text([page], max_words=2) == "scanned words"


def test_collect_sample_text_ignores_image_blocks():
    page = PageData(page_num=1, is_ocr=False)
    page.blocks = [
        ImageBlock(bbox=(0, 0, 10, 10), xref=1),
        TextBlock(bbox=(0, 20, 100, 40), text="real text"),
    ]
    assert collect_sample_text([page], max_words=10) == "real text"


def test_collect_sample_text_empty_when_no_text():
    page = PageData(page_num=1, is_ocr=False)
    assert collect_sample_text([page], max_words=10) == ""


# --- T-067: truncated/empty model output on the language + summary calls -----


def _stub_client(text: str, finish_reason: str = "stop"):
    create = lambda **kwargs: make_response(text, finish_reason=finish_reason)  # noqa: E731
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


_CFG = SimpleNamespace(
    api=SimpleNamespace(model="test-model", temperature=0.0),
    document_summary=SimpleNamespace(sample_words=50, prompt="Summarise."),
)


def test_truncated_language_detection_falls_back_loudly(tmp_path: Path, caplog):
    """An 8-token cap truncation means the model rambled — the cut-off text is
    NOT a language name and must not be cached as one (T-067)."""
    client = _stub_client("The language of this text", finish_reason="length")
    with caplog.at_level(logging.WARNING, logger="figmark.summarize"):
        got = detect_language(client, [_text_page(1, "some words")], _CFG, tmp_path / "lang.txt")
    assert got == "", "fall back to the document-language instruction"
    assert "token cap" in caplog.text, "the fallback is announced"
    assert not (tmp_path / "lang.txt").exists(), "garbage is not cached as the language"


def test_empty_language_detection_falls_back_loudly(tmp_path: Path, caplog):
    client = _stub_client("   ")
    with caplog.at_level(logging.WARNING, logger="figmark.summarize"):
        got = detect_language(client, [_text_page(1, "some words")], _CFG, tmp_path / "lang.txt")
    assert got == ""
    assert "empty content" in caplog.text


def test_truncated_summary_is_used_but_not_cached(tmp_path: Path, caplog):
    """T-033 semantics: a partial summary still helps THIS run, but it is
    announced and never cached — the next run regenerates."""
    client = _stub_client("A report about qu", finish_reason="length")
    with caplog.at_level(logging.WARNING, logger="figmark.summarize"):
        got = summarize_document(
            client, [_text_page(1, "some words")], _CFG, tmp_path / "sum.txt", "English"
        )
    assert got == "A report about qu"
    assert "truncated" in caplog.text
    assert not (tmp_path / "sum.txt").exists(), "a partial summary must not be cached"


def test_complete_summary_still_caches(tmp_path: Path):
    client = _stub_client("A quarterly report.")
    got = summarize_document(
        client, [_text_page(1, "some words")], _CFG, tmp_path / "sum.txt", "English"
    )
    assert got == "A quarterly report."
    assert (tmp_path / "sum.txt").read_text(encoding="utf-8") == "A quarterly report."
