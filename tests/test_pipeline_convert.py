"""Phase 1: the shared in-process pipeline entry point ``convert``.

These run offline with an injected fake client — no network, no real model.
"""

from __future__ import annotations

from pathlib import Path

from figmark.config import load_config
from figmark.parallel import Job, run_jobs
from figmark.pipeline import ConversionResult, convert

from .fakes import DETECTED_LANGUAGE, FakeClient, synthetic_pdf


def test_convert_returns_markdown_and_paths(env_with_key, project_root: Path, tmp_path: Path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    client = FakeClient("En bild på en katt.")

    result = convert(pdf, cfg, tmp_path / "output", client=client, quiet=True)

    assert isinstance(result, ConversionResult)
    assert "En bild på en katt." in result.markdown
    assert result.markdown_path.exists()
    assert result.markdown_path.read_text(encoding="utf-8") == result.markdown
    assert result.raw_text_path.exists()
    assert result.page_count == 1
    assert result.figure_count == 1
    assert result.skipped_count == 0
    assert result.language == DETECTED_LANGUAGE


def test_convert_uses_injected_client_without_monkeypatch(
    env_with_key, project_root: Path, tmp_path: Path
):
    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    client = FakeClient("En bild på en katt.")

    convert(pdf, cfg, tmp_path / "output", client=client, quiet=True)

    # The injected client did all the work (no monkeypatching of module globals).
    assert client.language_prompts, "language detection should have used the injected client"
    assert client.describe_prompts, "the image should have been described via the injected client"


def test_convert_skip_marker_drops_figure(env_with_key, project_root: Path, tmp_path: Path):
    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    client = FakeClient("[SKIP]")

    result = convert(pdf, cfg, tmp_path / "output", client=client, quiet=True)

    assert result.figure_count == 0
    assert result.skipped_count == 1
    assert "](images/" not in result.markdown


def test_run_jobs_quiet_mode_runs_without_live_view():
    results: dict[str, str] = {}
    jobs = [
        Job(label="a", func=lambda: "ra", on_done=lambda t: results.__setitem__("a", t)),
        Job(label="b", func=lambda: "rb", on_done=lambda t: results.__setitem__("b", t)),
    ]
    run_jobs(jobs, max_workers=2, header="test", quiet=True)
    assert results == {"a": "ra", "b": "rb"}
