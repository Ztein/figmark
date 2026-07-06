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

    # T-067 additions to the fingerprint: the OCR language shapes context/
    # detection on scanned pages, the summary sample size shapes the summary
    # every description receives — both must miss, not silently reuse.
    cfg.ocr.language = "eng"
    ocr_changed = FakeClient("A picture of a cat.")
    convert(pdf, cfg, out, client=ocr_changed, quiet=True)
    assert len(ocr_changed.describe_prompts) == n_first, "ocr.language change must miss"

    cfg.document_summary.sample_words += 50
    sample_changed = FakeClient("A picture of a cat.")
    convert(pdf, cfg, out, client=sample_changed, quiet=True)
    assert len(sample_changed.describe_prompts) == n_first, "sample_words change must miss"


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


def test_same_embedded_image_across_pages_is_described_once(
    env_with_key, project_root: Path, tmp_path: Path
):
    """One embedded image drawn on three pages → one description API call,
    reused on every page (T-054: LibreOffice PDFs repeat header/logo images
    on every page; native PDFs repeat watermarks the same way)."""
    import fitz

    pdf_path = tmp_path / "repeat.pdf"
    doc = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 120))
    pix.set_rect(pix.irect, (200, 120, 40))
    xref = 0
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 60), f"Page {i + 1} body text. " * 20)
        if i == 0:
            xref = page.insert_image(fitz.Rect(72, 300, 192, 420), pixmap=pix)
        else:
            page.insert_image(fitz.Rect(72, 300, 192, 420), xref=xref)
    doc.save(pdf_path)
    doc.close()

    cfg = load_config(project_root / "config.example.yaml")
    client = FakeClient("En återkommande logotyp.")
    result = convert(pdf_path, cfg, tmp_path / "output", client=client, quiet=True)

    assert len(client.describe_prompts) == 1, "identical embedded images share one call"
    assert result.markdown.count("En återkommande logotyp.") == 3, (
        "every page still carries the description"
    )


def test_diagram_regions_are_scheduled_for_description(
    env_with_key, project_root: Path, tmp_path: Path
):
    """Regression guard: a detected diagram region MUST produce a description
    job. (A refactor once left the diagram loop outside the per-page loop —
    diagrams silently stopped being described, and no offline test caught it.)"""
    from .test_shared_description_cache import _pdf_with_diagram

    pdf = _pdf_with_diagram(tmp_path / "chart.pdf", "Quarterly figures. ")
    cfg = load_config(project_root / "config.example.yaml")
    client = FakeClient("Ett stapeldiagram.")

    result = convert(pdf, cfg, tmp_path / "output", client=client, quiet=True)

    assert len(client.describe_prompts) >= 1, "the diagram region must be described"
    assert result.figure_count >= 1
    assert "Ett stapeldiagram." in result.markdown
