"""Unit tests for the significance gate and prompt composition (offline, no API)."""

from __future__ import annotations

from figmark.context import ContextText
from figmark.describe import SKIP_MARKER, compose_prompt, is_skip, language_instruction
from figmark.output import PageData, to_markdown


def test_is_skip_detects_marker():
    assert is_skip(SKIP_MARKER) is True
    assert is_skip("  [skip]  ") is True
    assert is_skip("[SKIP] decorative logo") is True
    assert is_skip("A photo of a cat.") is False
    assert is_skip("") is False
    assert is_skip(None) is False


def test_compose_prompt_plain_task_when_no_extras():
    assert compose_prompt("Describe this.") == "Describe this."


def test_language_instruction_auto_says_match_document():
    for value in ("auto", "AUTO", "", "document"):
        clause = language_instruction(value)
        assert "same language as the document" in clause.lower()


def test_language_instruction_explicit_forces_language():
    assert language_instruction("English") == "Write your answer in English."
    assert language_instruction("svenska") == "Write your answer in svenska."


def test_compose_prompt_appends_language_clause_when_given():
    out = compose_prompt("Describe this.", language="English")
    assert out.startswith("Describe this.")
    assert "Write your answer in English." in out


def test_compose_prompt_no_language_clause_by_default():
    # language=None (the default) must not inject any language instruction.
    assert "language" not in compose_prompt("Describe this.").lower()


def test_compose_prompt_appends_significance_instruction():
    out = compose_prompt("Describe this.", significance=True)
    assert out.startswith("Describe this.")
    assert SKIP_MARKER in out


def test_compose_prompt_orders_summary_then_context_then_task():
    ctx = ContextText(before="words before", after="words after")
    out = compose_prompt(
        "Describe this.",
        doc_summary="A monetary policy report.",
        context=ctx,
        significance=True,
    )
    # Document type comes first, then the text context, then the task.
    assert out.index("[Document type]") < out.index("before the image") < out.index("[Task]")
    assert "A monetary policy report." in out
    assert SKIP_MARKER in out  # significance instruction lives under [Task]


def test_compose_prompt_summary_without_context():
    out = compose_prompt("Describe this.", doc_summary="A report.")
    assert "[Document type]" in out
    assert "A report." in out
    assert "[Task]" in out


def test_skip_marked_description_is_not_rendered():
    """A decorative image whose description is the skip marker is left out of the MD."""
    page = PageData(page_num=1, is_ocr=True)
    page.ocr_text = "Body text."
    from pathlib import Path

    from figmark.images import ExtractedImage

    page.images = [
        ExtractedImage(
            path=Path("/tmp/out/images/page-001-img-01.png"),
            page_num=1,
            index=1,
            xref=9,
            bbox=(0, 0, 10, 10),
        )
    ]
    page.descriptions = {9: SKIP_MARKER}

    md = to_markdown([page])
    assert "Body text." in md
    assert "](images/" not in md, "a skip-marked image must not be embedded"
