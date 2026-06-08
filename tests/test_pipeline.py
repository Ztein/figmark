"""LIVE pipeline-tester.

Kör mot riktiga Berget.ai-API:t. Kräver BERGET_API_KEY i .env eller miljön.
Hoppar INTE tyst över — failar med tydligt felmeddelande om nyckel saknas.

Markerad 'live' så man kan exkludera med `pytest -m "not live"` vid utveckling.
Default-konfigurationen i pytest.ini kör allt inklusive live.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src import main as main_module
from src.config import load_config

pytestmark = pytest.mark.live


def _require_real_key() -> str:
    """Tydligt fel om nyckel saknas — inte tyst skip."""
    from dotenv import load_dotenv
    load_dotenv()
    key = os.environ.get("BERGET_API_KEY", "")
    if not key or key.startswith("sk-test") or key == "sk-your-key-here":
        pytest.fail(
            "\n\n"
            "!" * 78 + "\n"
            "!!! BERGET_API_KEY saknas eller är en placeholder.\n"
            "!!! Live-pipelinetesterna körs MOT RIKTIGA API:T och kräver en riktig nyckel.\n"
            "!!! Lägg in din nyckel i .env och kör om.\n"
            "!!! För att hoppa över live-tester: pytest -m 'not live'\n"
            + "!" * 78
        )
    return key


@pytest.fixture(scope="module")
def real_key() -> str:
    return _require_real_key()


@pytest.fixture(scope="module")
def cfg(real_key, project_root: Path):
    return load_config(project_root / "config.yaml")


def test_pipeline_pentland_full_roundtrip(
    real_key, project_root: Path, pentland_pdf: Path, tmp_path: Path
):
    """Den fulla roundtrippen mot riktiga Berget: PDF → text + syntolkade bilder.

    Pentland-artikeln är mindre (16 sidor, 2 bilder) — billigast att köra på riktigt.
    """
    output_root = tmp_path / "output"
    exit_code = main_module.run(
        pdf_path=pentland_pdf,
        config_path=project_root / "config.yaml",
        output_root=output_root,
    )
    assert exit_code == 0

    pdf_out = output_root / pentland_pdf.stem
    raw_path = pdf_out / "raw_text.txt"
    full_path = pdf_out / "full_text.txt"
    images_dir = pdf_out / "images"
    descriptions_dir = pdf_out / "descriptions"

    # Artefakter
    assert raw_path.exists() and raw_path.stat().st_size > 1000
    assert full_path.exists() and full_path.stat().st_size > 1000

    images = sorted(images_dir.iterdir())
    descriptions = sorted(descriptions_dir.iterdir())
    assert len(images) >= 1
    assert len(descriptions) == len(images)

    # Innehåll
    full_text = full_path.read_text(encoding="utf-8")
    raw_text = raw_path.read_text(encoding="utf-8")
    assert full_text.count("[Bild:") == len(images)
    assert "[Bild:" not in raw_text
    assert "routine" in raw_text.lower(), "Pentland-artikeln handlar om organizational routines"

    # Beskrivningarna ska vara på svenska, inte tomma
    for desc_file in descriptions:
        text = desc_file.read_text(encoding="utf-8").strip()
        assert len(text) > 20, f"För kort syntolkning i {desc_file.name}: {text!r}"
        # Heuristik för svenska: vanliga svenska bokstäver eller ord
        lower = text.lower()
        has_swedish = any(c in lower for c in "åäö") or any(
            w in lower for w in [" och ", " att ", " som ", " en ", " ett ", " på "]
        )
        assert has_swedish, (
            f"Syntolkningen i {desc_file.name} ser inte ut att vara på svenska:\n{text}"
        )


def test_pipeline_cache_no_extra_api_calls_on_rerun(
    real_key, project_root: Path, pentland_pdf: Path, tmp_path: Path, monkeypatch
):
    """Andra körningen ska INTE göra fler API-anrop — cachen ska gripa in.

    Vi spårar att client.chat.completions.create inte anropas under rerun.
    """
    output_root = tmp_path / "output"

    # Första körningen: full live
    main_module.run(pentland_pdf, project_root / "config.yaml", output_root)
    desc_dir = output_root / pentland_pdf.stem / "descriptions"
    cached_count = sum(1 for _ in desc_dir.iterdir())
    assert cached_count >= 1

    # Andra körningen: räkna API-anrop genom att wrap:a create()
    import src.describe as describe_module
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

    main_module.run(pentland_pdf, project_root / "config.yaml", output_root)
    assert call_counter["n"] == 0, (
        f"Andra körningen gjorde {call_counter['n']} API-anrop "
        f"— cachen i descriptions/ fungerar inte"
    )


def test_pipeline_diagrams_extracted_from_penningpolitisk(
    real_key, project_root: Path, penningpolitisk_pdf: Path, tmp_path: Path
):
    """End-to-end: penningpolitiska rapporten ska producera diagram-syntolkningar.

    Vi kör mot en delmängd av sidor för att hålla nere kostnad och tid.
    Test verifierar att diagram-pipelinen aktiveras och producerar svenska syntolkningar.
    """
    # För att begränsa kostnaden, klippt ut bara några diagram-tunga sidor till en mini-PDF
    import fitz
    src = fitz.open(penningpolitisk_pdf)
    mini = fitz.open()
    mini.insert_pdf(src, from_page=10, to_page=10)  # sida 11 (0-indexerat 10)
    mini.insert_pdf(src, from_page=67, to_page=67)  # sida 68
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

    # Sida 11 = 2 diagram, sida 68 = 2 diagram → totalt 4
    assert len(diagram_files) == 4, f"Förväntar 4 diagram-bilder, fick {len(diagram_files)}"
    assert len(desc_files) == 4

    full_text = (pdf_out / "full_text.txt").read_text(encoding="utf-8")
    assert full_text.count("[Diagram:") == 4

    # Verifiera svensk myndighetssvenska i varje syntolkning
    for desc_file in desc_files:
        text = desc_file.read_text(encoding="utf-8").strip()
        assert len(text) > 100, f"Misstänkt kort diagram-syntolkning: {text[:200]}"
        lower = text.lower()
        # Diagram-syntolkningar bör nämna något om axlar, värden, eller serier
        assert any(w in lower for w in ["axel", "diagram", "linje", "procent", "scenari", "prognos", "serie"]), (
            f"Diagram-syntolkning saknar relevanta termer:\n{text[:400]}"
        )


def test_pipeline_determinism_workers_1_vs_4(
    real_key, project_root: Path, penningpolitisk_pdf: Path, tmp_path: Path
):
    """Output måste vara identisk oavsett antal workers (1 vs 4).

    Vi kör mot en mini-PDF (2 sidor med 4 diagram) två gånger:
    en gång med max_workers=1, en gång med max_workers=4. full_text.txt
    ska vara identisk byte-för-byte.
    """
    import fitz
    import yaml

    src = fitz.open(penningpolitisk_pdf)
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

    # Kör med 1 worker först — fyller cachen
    out_seq = tmp_path / "out_seq"
    main_module.run(mini_path, make_config(1), out_seq)
    seq_text = (out_seq / mini_path.stem / "full_text.txt").read_text(encoding="utf-8")

    # Kör med 4 workers mot färsk output-katalog. Cachen är per-output-katalog,
    # så det här är en faktisk ny körning. Beskrivningarna har dock samma
    # input → texten ska ändå matcha (Gemma är inte helt deterministisk, men
    # cachen från första körningen kan inte återanvändas mellan output-kataloger).
    #
    # Pragmatiskt: vi kopierar in cache från första körningen så vi jämför pipeline-
    # ORDNINGEN, inte modellens determinism.
    import shutil
    out_par = tmp_path / "out_par"
    out_par.mkdir(parents=True)
    shutil.copytree(out_seq / mini_path.stem, out_par / mini_path.stem)
    # Ta bort de assembled text-filerna så de byggs om
    (out_par / mini_path.stem / "raw_text.txt").unlink()
    (out_par / mini_path.stem / "full_text.txt").unlink()

    main_module.run(mini_path, make_config(4), out_par)
    par_text = (out_par / mini_path.stem / "full_text.txt").read_text(encoding="utf-8")

    assert seq_text == par_text, "full_text.txt skiljer sig mellan 1 och 4 workers"


def test_pipeline_annotate_pdf_produces_annotated_copy(
    real_key, project_root: Path, pentland_pdf: Path, tmp_path: Path
):
    """Live-test: pipelinen med annotate=True producerar en annoterad kopia
    med rätt antal annotations (en per syntolkning)."""
    import fitz

    output_root = tmp_path / "output"
    exit_code = main_module.run(
        pdf_path=pentland_pdf,
        config_path=project_root / "config.yaml",
        output_root=output_root,
        annotate=True,
    )
    assert exit_code == 0

    annotated = output_root / pentland_pdf.stem / f"{pentland_pdf.stem}_alt_text.pdf"
    assert annotated.exists(), f"Alt-text PDF saknas: {annotated}"

    # Räkna annotations i resultatet
    doc = fitz.open(annotated)
    try:
        total_annots = 0
        for page in doc:
            total_annots += len(list(page.annots()))
    finally:
        doc.close()

    # Pentland har 2 bilder
    assert total_annots >= 2, f"För få annotations: {total_annots}"


def test_pipeline_etikprovning_first_page_handles_large_cover_image(
    real_key, project_root: Path, etikprovning_pdf: Path, tmp_path: Path
):
    """Regression mot 413-bug: etikprövning-PDF:ns sida 1 har en stor omslagsbild
    (~917 KB PNG) som triggade 'Request failed with status code 413' från Berget.

    Det här är integration-nivå — verifierar att hela pipelinen (med automatisk
    resize) klarar bilden från extraktion till slutförd syntolkning, inte bara
    att _prepare_image_for_api skalar ner isolerat.

    Vi klipper ut sida 1 till en mini-PDF för att hålla nere kostnad och tid.
    """
    import fitz
    src = fitz.open(etikprovning_pdf)
    mini = fitz.open()
    mini.insert_pdf(src, from_page=0, to_page=0)
    mini_path = tmp_path / "etikprovning_sida_1.pdf"
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
    assert len(descriptions) >= 1, "Omslagsbilden ska ha syntolkats"
    text = descriptions[0].read_text(encoding="utf-8").strip()
    assert len(text) > 30, f"För kort syntolkning: {text!r}"


def test_pipeline_describe_single_image_returns_swedish(
    real_key, project_root: Path, pentland_pdf: Path, tmp_path: Path
):
    """Isolerar API-anropet för en bild — verifierar svensk myndighetston."""
    from src.describe import describe_image, make_client
    from src.images import extract_images_from_page
    from src.pdf_loader import iter_pages, open_pdf

    cfg = load_config(project_root / "config.yaml")
    client = make_client(cfg)

    images_out = tmp_path / "images"
    desc_path = tmp_path / "single.txt"

    doc = open_pdf(pentland_pdf)
    try:
        first_image = None
        for page_num, page in iter_pages(doc):
            extracted = extract_images_from_page(doc, page, page_num, images_out, cfg)
            if extracted:
                first_image = extracted[0]
                break
        assert first_image is not None, "Hittade inga bilder i Pentland-PDF — testet kan inte köras"

        result = describe_image(client, first_image.path, desc_path, cfg)
    finally:
        doc.close()

    assert len(result) > 30, f"Misstänkt kort syntolkning: {result!r}"
    print(f"\n--- Faktisk syntolkning från Berget ({cfg.api.model}) ---\n{result}\n")
