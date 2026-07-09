"""Summarise the document once, to use as context for every figure description.

A diagram or photo is interpreted better when the model knows what kind of
document it sits in. We take the first N words of the extracted text, ask the
model for a one/two-sentence summary of the document type and subject, and feed
that summary into each image/diagram description prompt.

The summary is cached on disk so re-runs don't pay for it again.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Config
from .describe import language_instruction

logger = logging.getLogger("figmark.summarize")

# Technical constant — the summary is meant to be short context, not a précis.
SUMMARY_MAX_TOKENS = 300

# Language detection: a small sample is plenty, and the answer is one word.
LANG_DETECT_WORDS = 120
LANG_DETECT_MAX_TOKENS = 8
LANG_DETECT_PROMPT = (
    "Identify the language of the following text. Answer with only the language "
    "name in English (for example: English, Swedish, German), and nothing else."
)


def detect_language(client, pages, cfg: Config, cache_path: Path) -> str:
    """Return the document's language name (e.g. "English"), or "" if unknown.

    A soft "answer in the document's language" instruction is unreliable against a
    prompt written in another language, so for `language.output: auto` we detect
    the name once and then instruct the model explicitly. Cached on disk.
    """
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    sample = collect_sample_text(pages, LANG_DETECT_WORDS)
    if not sample:
        return ""

    response = client.chat.completions.create(
        model=cfg.api.model,
        temperature=cfg.api.temperature,
        max_tokens=LANG_DETECT_MAX_TOKENS,
        messages=[{"role": "user", "content": f"{LANG_DETECT_PROMPT}\n\nText:\n{sample}"}],
    )
    choice = response.choices[0]
    name = (choice.message.content or "").strip().strip(".").strip()
    if getattr(choice, "finish_reason", None) == "length":
        # The answer should be ONE word inside an 8-token cap — a truncation
        # means the model rambled and the text is a cut-off sentence, not a
        # language name. Announce and fall back to the document-language
        # instruction instead of caching garbage as the language (T-067).
        logger.warning(
            "language detection hit the %d-token cap (finish_reason=length, got %r) "
            "— falling back to the document-language instruction",
            LANG_DETECT_MAX_TOKENS,
            name,
        )
        return ""
    if not name:
        logger.warning(
            "language detection returned empty content — "
            "falling back to the document-language instruction"
        )
        return ""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(name, encoding="utf-8")
    return name


def collect_sample_text(pages, max_words: int) -> str:
    """Gather up to max_words of leading text from the pages, in reading order."""
    from .pdf_loader import TextBlock

    words: list[str] = []
    for page in pages:
        if page.is_ocr:
            text = page.ocr_text or ""
        else:
            text = " ".join(b.text for b in page.blocks if isinstance(b, TextBlock))
        if text.strip():
            words.extend(text.split())
        if len(words) >= max_words:
            break
    return " ".join(words[:max_words]).strip()


def summarize_document(client, pages, cfg: Config, cache_path: Path, language: str) -> str:
    """Return a short document-type summary, using the cache when present.

    `language` is the resolved output language (e.g. "English"); it controls the
    summary's language. Returns "" if there is no text to summarise.
    """
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    sample = collect_sample_text(pages, cfg.document_summary.sample_words)
    if not sample:
        return ""

    user_text = (
        f"{cfg.document_summary.prompt}\n\n"
        f"{language_instruction(language)}\n\n"
        f"[Document text]\n{sample}"
    )
    response = client.chat.completions.create(
        model=cfg.api.model,
        temperature=cfg.api.temperature,
        max_tokens=SUMMARY_MAX_TOKENS,
        messages=[{"role": "user", "content": user_text}],
    )
    choice = response.choices[0]
    text = (choice.message.content or "").strip()
    if getattr(choice, "finish_reason", None) == "length":
        # T-033 semantics, T-067 audit: keep the partial for this run (it is
        # still useful context) but say so, and do NOT cache it — the next run
        # regenerates instead of inheriting a cut-off summary.
        logger.warning(
            "document summary was truncated at the %d-token cap (finish_reason=length); "
            "using it for this run but not caching it",
            SUMMARY_MAX_TOKENS,
        )
        return text
    if not text:
        logger.warning("document summary returned empty content — continuing without a summary")
        return ""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text
