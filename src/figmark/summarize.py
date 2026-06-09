"""Summarise the document once, to use as context for every figure description.

A diagram or photo is interpreted better when the model knows what kind of
document it sits in. We take the first N words of the extracted text, ask the
model for a one/two-sentence summary of the document type and subject, and feed
that summary into each image/diagram description prompt.

The summary is cached on disk so re-runs don't pay for it again.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .describe import language_instruction

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
        max_tokens=LANG_DETECT_MAX_TOKENS,
        messages=[{"role": "user", "content": f"{LANG_DETECT_PROMPT}\n\nText:\n{sample}"}],
    )
    name = (response.choices[0].message.content or "").strip().strip(".").strip()
    if name:
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
        max_tokens=SUMMARY_MAX_TOKENS,
        messages=[{"role": "user", "content": user_text}],
    )
    text = (response.choices[0].message.content or "").strip()
    if text:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
    return text
