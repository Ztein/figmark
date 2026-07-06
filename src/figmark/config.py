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

from .input_formats import OFFICE_FORMATS, validate_formats


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
class TablesConfig:
    # When enabled, ruled data tables are detected (PyMuPDF) and emitted as
    # Markdown tables. Conservative filters keep it silent on chart-heavy docs.
    enabled: bool


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
class OfficeConfig:
    # Resolved LibreOffice binary + the per-file conversion timeout. Only present
    # when Office formats are configured; resolution fails loud at load (T-054).
    soffice_path: str
    timeout_seconds: float


@dataclass
class InputConfig:
    # Accepted input document formats (T-054). Enforced by content sniffing at
    # both HTTP surfaces; an upload outside the list gets a 415 naming the set.
    formats: list[str]
    office: OfficeConfig | None = None


@dataclass
class CacheConfig:
    # Cross-request cache for the HTTP surface (T-060): document results (and,
    # with T-061, shared figure descriptions). LRU-evicted above max_size_mb;
    # entries expire max_age_hours after their last access (a hit resets it).
    enabled: bool
    max_size_mb: int = 0
    max_age_hours: float = 0.0
    # T-063: description reuse across documents. True (the default) reuses a
    # figure description wherever the same image bytes appear — the cache's
    # main saving. False keys descriptions by document too: a re-upload of the
    # SAME document still reuses, but context bleed between documents stops
    # (privacy-strict deployments).
    share_descriptions_across_documents: bool = True


@dataclass
class Config:
    api: ApiConfig
    input: InputConfig
    cache: CacheConfig
    ocr: OcrConfig
    description: DescriptionConfig
    diagrams: DiagramsConfig
    tables: TablesConfig
    concurrency: ConcurrencyConfig
    context: ContextConfig
    significance: SignificanceConfig
    document_summary: DocumentSummaryConfig
    language: LanguageConfig


def _require(section: dict, key: str, section_name: str):
    """Fetch a required field. Fails loudly if it is missing.

    A whitespace-only string counts as missing (T-067): the loaders strip
    prompts after this check, and an enabled feature with a blank prompt would
    otherwise run with a degenerate task — silently.
    """
    value = section.get(key)
    if key not in section or value in (None, "") or (isinstance(value, str) and not value.strip()):
        raise RuntimeError(
            f"{section_name}.{key} is missing from config.yaml — this field is required."
        )
    return value


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

    input_raw = raw.get("input") or {}
    if "formats" not in input_raw:
        raise RuntimeError(
            "input.formats is missing from config.yaml — this field is required. "
            'List the accepted input document formats, e.g. ["pdf", "epub"].'
        )
    formats_raw = input_raw["formats"]
    if not isinstance(formats_raw, list):
        raise RuntimeError("input.formats must be a list of format names.")
    # Office formats need a working LibreOffice — resolved at load so a
    # misconfiguration fails at startup, never as a 500 at request time (T-054).
    office_cfg: OfficeConfig | None = None
    wants_office = any(str(f).strip().lower().lstrip(".") in OFFICE_FORMATS for f in formats_raw)
    if wants_office:
        from .office import find_soffice

        office_raw = input_raw.get("office") or {}
        binary = find_soffice(str(office_raw.get("soffice_path") or "") or None)
        if binary is None:
            raise RuntimeError(
                "input.formats includes an Office format (docx/xlsx/pptx) but "
                "LibreOffice (soffice) was not found. Use the Office image "
                "variant, install LibreOffice, or set input.office.soffice_path "
                "(T-054)."
            )
        timeout = float(_require(office_raw, "timeout_seconds", "input.office"))
        if timeout <= 0:
            raise RuntimeError("input.office.timeout_seconds must be positive.")
        office_cfg = OfficeConfig(soffice_path=binary, timeout_seconds=timeout)
    input_cfg = InputConfig(
        formats=validate_formats(formats_raw, office_available=office_cfg is not None),
        office=office_cfg,
    )

    cache_raw = raw.get("cache") or {}
    if "enabled" not in cache_raw:
        raise RuntimeError("cache.enabled is missing from config.yaml — this field is required.")
    cache_enabled = bool(cache_raw["enabled"])
    if cache_enabled:
        max_size_mb = int(_require(cache_raw, "max_size_mb", "cache"))
        max_age_hours = float(_require(cache_raw, "max_age_hours", "cache"))
        if max_size_mb <= 0 or max_age_hours <= 0:
            raise RuntimeError("cache.max_size_mb and cache.max_age_hours must be positive.")
    else:
        max_size_mb = int(cache_raw.get("max_size_mb", 0) or 0)
        max_age_hours = float(cache_raw.get("max_age_hours", 0) or 0)
    cache = CacheConfig(
        enabled=cache_enabled,
        max_size_mb=max_size_mb,
        max_age_hours=max_age_hours,
        share_descriptions_across_documents=bool(
            cache_raw.get("share_descriptions_across_documents", True)
        ),
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

    tables_raw = raw.get("tables") or {}
    if "enabled" not in tables_raw:
        raise RuntimeError("tables.enabled is missing from config.yaml — this field is required.")
    tables = TablesConfig(enabled=bool(tables_raw["enabled"]))

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
        input=input_cfg,
        cache=cache,
        ocr=ocr,
        description=description,
        diagrams=diagrams,
        tables=tables,
        concurrency=concurrency,
        context=context,
        significance=significance,
        document_summary=document_summary,
        language=language,
    )
