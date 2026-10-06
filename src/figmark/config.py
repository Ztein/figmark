"""Run configuration: which model describes figures, and from where.

A YAML file (default ./figmark.yaml, or $FIGMARK_CONFIG). Keys are named by
environment variable, never written in the file. Without a `figures` section
figmark converts text and structure only and says so.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class FigureModel:
    base_url: str  # OpenAI-compatible, e.g. http://localhost:11434/v1
    model: str
    api_key_env: str | None = None
    params: dict = field(default_factory=dict)  # extra request fields, e.g. reasoning_effort
    prompt: str | None = None  # None: Docling's built-in prompt
    concurrency: int = 4
    timeout: float = 120.0
    cache: str | bool = True  # True: ~/.cache/figmark/descriptions.sqlite; a path; or false to describe every time

    @property
    def api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        key = os.environ.get(self.api_key_env)
        if not key:
            raise SystemExit(f"figures.api_key_env names {self.api_key_env}, which is not set")
        return key


@dataclass(frozen=True)
class Config:
    figures: FigureModel | None = None


def load(path: str | Path | None = None) -> Config:
    path = Path(path or os.environ.get("FIGMARK_CONFIG", "figmark.yaml"))
    if not path.exists():
        return Config()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    fig = raw.get("figures")
    return Config(figures=FigureModel(**fig) if fig else None)
