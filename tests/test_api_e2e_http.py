"""Phase 3: real figmark OpenAI client → mock server → Markdown, fully offline.

This proves the actual HTTP path (the OpenAI SDK making real requests) works
against any OpenAI-compatible endpoint, using the mock as the stand-in vision
model — the air-gapped end-to-end proof without a real LLM.
"""

from __future__ import annotations

from pathlib import Path

from figmark.config import load_config
from figmark.describe import make_client
from figmark.pipeline import convert

from .fakes import synthetic_pdf


def test_real_client_against_mock_server(
    env_with_key, project_root: Path, tmp_path: Path, mock_llm_server: str
):
    cfg = load_config(project_root / "config.example.yaml")
    cfg.api.base_url = f"{mock_llm_server}/v1"  # point the real client at the mock

    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    result = convert(pdf, cfg, tmp_path / "out", client=make_client(cfg), quiet=True)

    assert "En bild på en katt." in result.markdown
    assert result.language == "Swedish"
    assert result.figure_count == 1
