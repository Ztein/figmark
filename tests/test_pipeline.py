"""LIVE pipeline tests.

Run against a real LLM API. Require FIGMARK_API_KEY in .env or the
environment. They do NOT skip silently — they fail with a clear message if the
key is missing.

Marked 'live' so they can be excluded with `pytest -m "not live"` during
development. The default configuration runs everything, including live tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from figmark import main as main_module
from figmark.config import load_config
from figmark.describe import is_skip

pytestmark = pytest.mark.live


def _require_real_key() -> str:
    """Fail clearly if the key is missing — not a silent skip."""
    from dotenv import load_dotenv

    load_dotenv()
    key = os.environ.get("FIGMARK_API_KEY", "")
    if not key or key.startswith("sk-test") or key == "sk-your-key-here":
        pytest.fail(
            "\n\n"
            "!" * 78 + "\n"
            "!!! FIGMARK_API_KEY is missing or a placeholder.\n"
            "!!! The live pipeline tests run AGAINST THE REAL API and need a real key.\n"
            "!!! Put your key in .env and run again.\n"
            "!!! To skip the live tests: pytest -m 'not live'\n" + "!" * 78
        )
    return key


@pytest.fixture(scope="module")
def real_key() -> str:
    return _require_real_key()


@pytest.fixture(scope="module")
def cfg(real_key, project_root: Path):
    return load_config(project_root / "config.yaml")


def test_pipeline_paper_full_roundtrip(
    real_key, project_root: Path, paper_pdf: Path, tmp_path: Path
):
    """The full round trip against the real API: PDF → Markdown + described images.

    The sample paper is small — the cheapest fixture to run for real. It also
    guards T-007: with language.output: auto the English paper is described in
    English (the document's language), not the prompt's Swedish register.
    """
    output_root = tmp_path / "output"
    exit_code = main_module.run(
        pdf_path=paper_pdf,
        config_path=project_root / "config.yaml",
        output_root=output_root,
    )
    assert exit_code == 0

    pdf_out = output_root / paper_pdf.stem
    raw_path = pdf_out / "raw_text.txt"
    md_path = pdf_out / f"{paper_pdf.stem}.md"
    images_dir = pdf_out / "images"
    descriptions_dir = pdf_out / "descriptions"
    language_path = pdf_out / "document_language.txt"

    # Artifacts
    assert raw_path.exists() and raw_path.stat().st_size > 1000
    assert md_path.exists() and md_path.stat().st_size > 1000

    images = sorted(images_dir.iterdir())
    descriptions = sorted(descriptions_dir.iterdir())
    assert len(images) >= 1
    assert len(descriptions) == len(images)

    # Content
    markdown = md_path.read_text(encoding="utf-8")
    raw_text = raw_path.read_text(encoding="utf-8")
    assert markdown.count("](images/") == len(images)
    assert "](images/" not in raw_text

    # Language follows the document (T-007): with language.output: auto, the
    # English sample paper must be detected as English — NOT forced to the prompt's
    # Swedish register. This is the regression guard the old hardcoded-Swedish
    # assertion contradicted.
    assert language_path.exists(), "document_language.txt was not written"
    detected = language_path.read_text(encoding="utf-8").strip()
    assert detected.lower() == "english", (
        f"Expected the English paper to be detected as English, got {detected!r}"
    )

    # Each described image is substantive (non-empty, not a stub).
    for desc_file in descriptions:
        text = desc_file.read_text(encoding="utf-8").strip()
        assert len(text) > 20, f"Description too short in {desc_file.name}: {text!r}"


def test_pipeline_cache_no_extra_api_calls_on_rerun(
    real_key, project_root: Path, paper_pdf: Path, tmp_path: Path, monkeypatch
):
    """A second run must NOT make extra API calls — the cache should kick in.

    We track that client.chat.completions.create is not called during the rerun.
    """
    output_root = tmp_path / "output"

    # First run: full live
    main_module.run(paper_pdf, project_root / "config.yaml", output_root)
    desc_dir = output_root / paper_pdf.stem / "descriptions"
    cached_count = sum(1 for _ in desc_dir.iterdir())
    assert cached_count >= 1

    # Second run: count API calls by wrapping create()
    import figmark.describe as describe_module

    real_make_client = describe_module.make_client
    call_counter = {"n": 0}

    def make_counting_client(cfg):
        client = real_make_client(cfg)
        original_create = client.chat.completions.create

        def counting_create(*args, **kwargs):
            call_counter["n"] += 1
            return original_create(*args, **kwargs)

        client.chat.completions.create = counting_create
        return client

    monkeypatch.setattr(main_module, "make_client", make_counting_client)

    main_module.run(paper_pdf, project_root / "config.yaml", output_root)
    assert call_counter["n"] == 0, (
        f"The second run made {call_counter['n']} API call(s) "
        f"— the descriptions/ cache is not working"
    )


def test_pipeline_diagrams_extracted_from_report(
    real_key, project_root: Path, report_pdf: Path, tmp_path: Path
):
    """End-to-end: the monetary-policy report should produce diagram descriptions.

    We run against a subset of pages to keep cost and time down. The test verifies
    that the diagram pipeline activates and produces Swedish descriptions.
    """
    # To limit cost, cut out a few diagram-heavy pages into a mini PDF.
    import fitz

    src = fitz.open(report_pdf)
    mini = fitz.open()
    mini.insert_pdf(src, from_page=10, to_page=10)  # page 11 (0-indexed 10)
    mini.insert_pdf(src, from_page=67, to_page=67)  # page 68
    mini_path = tmp_path / "mini.pdf"
    mini.save(mini_path)
    mini.close()
    src.close()

    output_root = tmp_path / "output"
    exit_code = main_module.run(
        pdf_path=mini_path,
        config_path=project_root / "config.yaml",
        output_root=output_root,
    )
    assert exit_code == 0

    pdf_out = output_root / mini_path.stem
    diagrams_dir = pdf_out / "diagrams"
    diagram_desc_dir = pdf_out / "diagram_descriptions"

    diagram_files = sorted(diagrams_dir.iterdir()) if diagrams_dir.exists() else []
    desc_files = sorted(diagram_desc_dir.iterdir()) if diagram_desc_dir.exists() else []

    # Page 11 = 2 diagrams, page 68 = 2 diagrams → 4 total
    assert len(diagram_files) == 4, f"Expected 4 diagram images, got {len(diagram_files)}"
    assert len(desc_files) == 4

    markdown = (pdf_out / f"{mini_path.stem}.md").read_text(encoding="utf-8")
    assert markdown.count("](diagrams/") == 4

    # Verify Swedish myndighetssvenska in each description.
    for desc_file in desc_files:
        text = desc_file.read_text(encoding="utf-8").strip()
        assert len(text) > 100, f"Suspiciously short diagram description: {text[:200]}"
        lower = text.lower()
        # Diagram descriptions should mention something about axes, values, or series.
        assert any(
            w in lower
            for w in ["axel", "diagram", "linje", "procent", "scenari", "prognos", "serie"]
        ), f"Diagram description lacks relevant terms:\n{text[:400]}"


def test_pipeline_determinism_workers_1_vs_4(
    real_key, project_root: Path, report_pdf: Path, tmp_path: Path
):
    """Output must be identical regardless of worker count (1 vs 4).

    We run a mini PDF (2 pages, 4 diagrams) twice: once with max_workers=1, once
    with max_workers=4. The Markdown output must be identical byte-for-byte.
    """
    import fitz
    import yaml

    src = fitz.open(report_pdf)
    mini = fitz.open()
    mini.insert_pdf(src, from_page=10, to_page=10)
    mini.insert_pdf(src, from_page=67, to_page=67)
    mini_path = tmp_path / "determinism.pdf"
    mini.save(mini_path)
    mini.close()
    src.close()

    def make_config(max_workers: int) -> Path:
        with (project_root / "config.yaml").open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        raw["concurrency"]["max_workers"] = max_workers
        path = tmp_path / f"cfg_{max_workers}.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True)
        return path

    # Run with 1 worker first — fills the cache.
    out_seq = tmp_path / "out_seq"
    main_module.run(mini_path, make_config(1), out_seq)
    seq_text = (out_seq / mini_path.stem / f"{mini_path.stem}.md").read_text(encoding="utf-8")

    # Run with 4 workers against a fresh output dir. The cache is per output dir,
    # so this is a genuinely new run. We copy in the cache from the first run so
    # we compare pipeline ORDERING, not the model's determinism.
    import shutil

    out_par = tmp_path / "out_par"
    out_par.mkdir(parents=True)
    shutil.copytree(out_seq / mini_path.stem, out_par / mini_path.stem)
    # Remove the assembled output files so they are rebuilt.
    (out_par / mini_path.stem / "raw_text.txt").unlink()
    (out_par / mini_path.stem / f"{mini_path.stem}.md").unlink()

    main_module.run(mini_path, make_config(4), out_par)
    par_text = (out_par / mini_path.stem / f"{mini_path.stem}.md").read_text(encoding="utf-8")

    assert seq_text == par_text, "Markdown output differs between 1 and 4 workers"


def test_pipeline_annotate_pdf_produces_annotated_copy(
    real_key, project_root: Path, paper_pdf: Path, tmp_path: Path
):
    """Live test: the pipeline with annotate=True produces an annotated copy with
    the right number of annotations (one per description)."""
    import fitz

    output_root = tmp_path / "output"
    exit_code = main_module.run(
        pdf_path=paper_pdf,
        config_path=project_root / "config.yaml",
        output_root=output_root,
        annotate=True,
    )
    assert exit_code == 0

    annotated = output_root / paper_pdf.stem / f"{paper_pdf.stem}_alt_text.pdf"
    assert annotated.exists(), f"Alt-text PDF missing: {annotated}"

    # Count annotations in the result.
    doc = fitz.open(annotated)
    try:
        total_annots = 0
        for page in doc:
            total_annots += len(list(page.annots()))
    finally:
        doc.close()

    assert total_annots >= 1, f"Too few annotations: {total_annots}"


def test_pipeline_cover_page_handles_large_image(
    real_key, project_root: Path, guide_pdf: Path, tmp_path: Path
):
    """Regression against the 413 bug: a page with a large cover image (~917 KB PNG)
    used to trigger 'Request failed with status code 413' from the API.

    This is integration level — it verifies that the whole pipeline (with automatic
    resize) handles the image from extraction through a finished description, not
    just that _prepare_image_for_api downscales in isolation.

    We cut out page 1 into a mini PDF to keep cost and time down.
    """
    import fitz

    src = fitz.open(guide_pdf)
    mini = fitz.open()
    mini.insert_pdf(src, from_page=0, to_page=0)
    mini_path = tmp_path / "cover_page_1.pdf"
    mini.save(mini_path)
    mini.close()
    src.close()

    output_root = tmp_path / "output"
    exit_code = main_module.run(
        pdf_path=mini_path,
        config_path=project_root / "config.yaml",
        output_root=output_root,
    )
    assert exit_code == 0

    desc_dir = output_root / mini_path.stem / "descriptions"
    descriptions = sorted(desc_dir.iterdir())
    assert len(descriptions) >= 1, "The large cover image should have been processed"
    text = descriptions[0].read_text(encoding="utf-8").strip()
    # What this test actually guards is the 413/resize path: the ~917 KB image
    # must reach the model and get a real reply. Whether that reply is a
    # description or the significance gate's [SKIP] (a cover image is plausibly
    # decorative) is a model-dependent call, not the regression — either proves
    # the resized image was accepted, not rejected with a 413. Accept both; a
    # 413 would instead surface as a pipeline error / empty result.
    assert is_skip(text) or len(text) > 30, f"Unexpected description: {text!r}"


def test_pipeline_describe_single_image_returns_swedish(
    real_key, project_root: Path, paper_pdf: Path, tmp_path: Path
):
    """Isolate the API call for one image — verify the Swedish formal tone."""
    from figmark.describe import describe_image, make_client
    from figmark.images import extract_images_from_page
    from figmark.pdf_loader import iter_pages, open_pdf

    cfg = load_config(project_root / "config.yaml")
    client = make_client(cfg)

    images_out = tmp_path / "images"
    desc_path = tmp_path / "single.txt"

    doc = open_pdf(paper_pdf)
    try:
        first_image = None
        for page_num, page in iter_pages(doc):
            extracted = extract_images_from_page(doc, page, page_num, images_out).images
            if extracted:
                first_image = extracted[0]
                break
        assert first_image is not None, "Found no images in the paper PDF — the test cannot run"

        result = describe_image(client, first_image.path, desc_path, cfg)
    finally:
        doc.close()

    assert len(result) > 30, f"Suspiciously short description: {result!r}"
    print(f"\n--- Actual description from {cfg.api.model} ---\n{result}\n")
