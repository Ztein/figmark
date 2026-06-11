"""Load and validate ``config.yaml`` into typed dataclasses.

No hidden defaults: every field the code relies on must be present in the file,
otherwise loading fails loudly with a message naming the missing field. Technical
tuning constants live as module-level constants in the modules that use them, not
here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class ApiConfig:
    base_url: str
    model: str
    api_key: str
    # Optional, provider-neutral cost estimation. Prices are per single token
    # (matching the OpenAI-compatible /v1/models pricing unit). Both must be set
    # together, or both omitted; never hardcode a provider's prices here.
    input_token_price: float | None = None
    output_token_price: float | None = None
    currency: str | None = None


@dataclass
class OcrConfig:
    language: str


@dataclass
class DescriptionConfig:
    prompt: str


@dataclass
class DiagramsConfig:
    enabled: bool
    prompt: str


@dataclass
class ConcurrencyConfig:
    max_workers: int


@dataclass
class ContextConfig:
    enabled: bool
    words_before: int
    words_after: int


@dataclass
class SignificanceConfig:
    enabled: bool


@dataclass
class DocumentSummaryConfig:
    enabled: bool
    sample_words: int
    prompt: str


@dataclass
class LanguageConfig:
    # Output language for descriptions/diagrams/summary. "auto" follows the
    # document's own language; otherwise a language name the model understands.
    output: str


@dataclass
class Config:
    api: ApiConfig
    ocr: OcrConfig
    description: DescriptionConfig
    diagrams: DiagramsConfig
    concurrency: ConcurrencyConfig
    context: ContextConfig
    significance: SignificanceConfig
    document_summary: DocumentSummaryConfig
    language: LanguageConfig


def _require(section: dict, key: str, section_name: str):
    """Fetch a required field. Fails loudly if it is missing."""
    if key not in section or section[key] in (None, ""):
        raise RuntimeError(
            f"{section_name}.{key} is missing from config.yaml — this field is required."
        )
    return section[key]


def _optional_price(value, key: str) -> float | None:
    """Parse an optional per-token price. Empty/absent → None; junk fails loudly."""
    if value in (None, ""):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"api.{key} must be a number (price per token) if set, got {value!r}."
        ) from exc
    if price < 0:
        raise RuntimeError(f"api.{key} must be non-negative, got {price}.")
    return price


def _resolve_api_key() -> str:
    """The key for the OpenAI-compatible endpoint.

    ``FIGMARK_API_KEY`` is the only supported name. Set ``FIGMARK_API_KEY=none``
    explicitly for endpoints that need no auth (e.g. a local vLLM/Ollama server).
    There is no fallback: an unset key fails loudly rather than silently using a
    key meant for a different variable.
    """
    api_key = os.environ.get("FIGMARK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "FIGMARK_API_KEY is not set. Copy .env.example to .env and add the key "
            "for your OpenAI-compatible vision endpoint (or set FIGMARK_API_KEY=none "
            "for an endpoint that requires no auth)."
        )
    return api_key


def load_config(config_path: str | Path = "config.yaml") -> Config:
    """Read config.yaml. Everything the code needs MUST be present — no hidden defaults.

    Technical constants (clustering thresholds, OCR thresholds, image-size filters,
    retry counts, render DPI, etc.) live as module-level constants in the modules
    that use them. Change them there if you need to tune.
    """
    load_dotenv()

    api_key = _resolve_api_key()

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    api_raw = raw.get("api") or {}
    in_price = _optional_price(api_raw.get("input_token_price"), "input_token_price")
    out_price = _optional_price(api_raw.get("output_token_price"), "output_token_price")
    if (in_price is None) != (out_price is None):
        raise RuntimeError(
            "api.input_token_price and api.output_token_price must both be set "
            "(for cost estimation) or both omitted."
        )
    api = ApiConfig(
        base_url=str(_require(api_raw, "base_url", "api")),
        model=str(_require(api_raw, "model", "api")),
        api_key=api_key,
        input_token_price=in_price,
        output_token_price=out_price,
        currency=(str(api_raw["currency"]).strip() if api_raw.get("currency") else None),
    )

    ocr_raw = raw.get("ocr") or {}
    ocr = OcrConfig(language=str(_require(ocr_raw, "language", "ocr")))

    desc_raw = raw.get("description") or {}
    description = DescriptionConfig(
        prompt=str(_require(desc_raw, "prompt", "description")).strip(),
    )

    diagrams_raw = raw.get("diagrams") or {}
    if "enabled" not in diagrams_raw:
        raise RuntimeError("diagrams.enabled is missing from config.yaml — this field is required.")
    enabled = bool(diagrams_raw["enabled"])
    if enabled:
        diagrams_prompt = str(_require(diagrams_raw, "prompt", "diagrams")).strip()
    else:
        diagrams_prompt = str(diagrams_raw.get("prompt", "")).strip()
    diagrams = DiagramsConfig(enabled=enabled, prompt=diagrams_prompt)

    concurrency_raw = raw.get("concurrency") or {}
    concurrency = ConcurrencyConfig(
        max_workers=int(_require(concurrency_raw, "max_workers", "concurrency")),
    )

    context_raw = raw.get("context") or {}
    if "enabled" not in context_raw:
        raise RuntimeError("context.enabled is missing from config.yaml — this field is required.")
    context = ContextConfig(
        enabled=bool(context_raw["enabled"]),
        words_before=int(_require(context_raw, "words_before", "context")),
        words_after=int(_require(context_raw, "words_after", "context")),
    )

    significance_raw = raw.get("significance") or {}
    if "enabled" not in significance_raw:
        raise RuntimeError(
            "significance.enabled is missing from config.yaml — this field is required."
        )
    significance = SignificanceConfig(enabled=bool(significance_raw["enabled"]))

    summary_raw = raw.get("document_summary") or {}
    if "enabled" not in summary_raw:
        raise RuntimeError(
            "document_summary.enabled is missing from config.yaml — this field is required."
        )
    summary_enabled = bool(summary_raw["enabled"])
    if summary_enabled:
        summary_words = int(_require(summary_raw, "sample_words", "document_summary"))
        summary_prompt = str(_require(summary_raw, "prompt", "document_summary")).strip()
    else:
        summary_words = int(summary_raw.get("sample_words", 0) or 0)
        summary_prompt = str(summary_raw.get("prompt", "")).strip()
    document_summary = DocumentSummaryConfig(
        enabled=summary_enabled,
        sample_words=summary_words,
        prompt=summary_prompt,
    )

    language_raw = raw.get("language") or {}
    language = LanguageConfig(output=str(_require(language_raw, "output", "language")).strip())

    return Config(
        api=api,
        ocr=ocr,
        description=description,
        diagrams=diagrams,
        concurrency=concurrency,
        context=context,
        significance=significance,
        document_summary=document_summary,
        language=language,
    )
