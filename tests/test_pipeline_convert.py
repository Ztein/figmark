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


def test_writes_figure_manifest(env_with_key, project_root: Path, tmp_path: Path):
    """A figures.json manifest is written and indexes the described figure with a
    path that resolves to a real file. (T-041)"""
    import json

    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    cfg = load_config(project_root / "config.example.yaml")
    result = convert(pdf, cfg, tmp_path / "output", client=FakeClient("En katt."), quiet=True)

    assert result.figures_manifest_path.exists()
    figures = json.loads(result.figures_manifest_path.read_text(encoding="utf-8"))
    assert len(figures) == 1  # the one embedded image
    fig = figures[0]
    assert fig["kind"] == "image"
    assert fig["page"] == 1
    assert fig["description"] == "En katt."
    assert fig["skipped"] is False
    assert fig["bbox"] is not None
    # the manifest path resolves to a real extracted file
    assert (result.output_dir / fig["path"]).exists()


def test_cache_misses_when_config_changes(env_with_key, project_root: Path, tmp_path: Path):
    """A description is reused only while the config that produced it is unchanged.
    Same config → cache hit (no API call); changed config → miss → regenerate. (T-034)"""
    pdf = synthetic_pdf(tmp_path / "doc.pdf")
    out = tmp_path / "output"
    cfg = load_config(project_root / "config.example.yaml")

    first = FakeClient("En bild på en katt.")
    convert(pdf, cfg, out, client=first, quiet=True)
    n_first = len(first.describe_prompts)
    assert n_first >= 1  # the embedded image was described

    # Same config, same output dir → every description is a cache hit.
    again = FakeClient("En bild på en katt.")
    convert(pdf, cfg, out, client=again, quiet=True)
    assert again.describe_prompts == []

    # Change a field that determines the output (the language) → cache miss.
    cfg.language.output = "English"
    changed = FakeClient("A picture of a cat.")
    convert(pdf, cfg, out, client=changed, quiet=True)
    assert len(changed.describe_prompts) == n_first


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
