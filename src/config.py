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
class Config:
    api: ApiConfig
    ocr: OcrConfig
    description: DescriptionConfig
    diagrams: DiagramsConfig
    concurrency: ConcurrencyConfig
    context: ContextConfig


def _require(section: dict, key: str, section_name: str):
    """Hämta ett obligatoriskt fält. Smäller högt om det saknas."""
    if key not in section or section[key] in (None, ""):
        raise RuntimeError(
            f"{section_name}.{key} saknas i config.yaml — detta fält är nödvändigt."
        )
    return section[key]


def load_config(config_path: str | Path = "config.yaml") -> Config:
    """Läs config.yaml. Allt som koden behöver MÅSTE finnas — inga gömda defaults.

    Tekniska konstanter (clustering-trösklar, OCR-trösklar, bildstorleksfilter,
    retry-antal, render-DPI etc.) finns som module-level konstanter i de moduler
    som använder dem. Ändra där om du behöver tuna.
    """
    load_dotenv()

    api_key = os.environ.get("BERGET_API_KEY")
    if not api_key:
        raise RuntimeError(
            "BERGET_API_KEY saknas. Kopiera .env.example till .env och fyll i din nyckel."
        )

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Hittar inte config-filen: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    api_raw = raw.get("api") or {}
    api = ApiConfig(
        base_url=str(_require(api_raw, "base_url", "api")),
        model=str(_require(api_raw, "model", "api")),
        api_key=api_key,
    )

    ocr_raw = raw.get("ocr") or {}
    ocr = OcrConfig(language=str(_require(ocr_raw, "language", "ocr")))

    desc_raw = raw.get("description") or {}
    description = DescriptionConfig(
        prompt=str(_require(desc_raw, "prompt", "description")).strip(),
    )

    diagrams_raw = raw.get("diagrams") or {}
    if "enabled" not in diagrams_raw:
        raise RuntimeError("diagrams.enabled saknas i config.yaml — detta fält är nödvändigt.")
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
        raise RuntimeError("context.enabled saknas i config.yaml — detta fält är nödvändigt.")
    context = ContextConfig(
        enabled=bool(context_raw["enabled"]),
        words_before=int(_require(context_raw, "words_before", "context")),
        words_after=int(_require(context_raw, "words_after", "context")),
    )

    return Config(
        api=api,
        ocr=ocr,
        description=description,
        diagrams=diagrams,
        concurrency=concurrency,
        context=context,
    )
