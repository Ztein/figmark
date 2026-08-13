"""T-054: extraction-quality expectations on the real Office corpus.

Each test encodes a manually verified truth about what figmark extracts from a
representative corpus document (testfiler/office-eval/, gitignored) — reviewed
by hand on 2026-07-02. They are regression guards for the Office path: heading
structure, ruled-table fidelity, figure counts after the phantom-image fix, and
the one-call-per-unique-image dedup.

Local-responsibility tier: skips cleanly without LibreOffice or the corpus
(CI has neither), like the live suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from figmark.config import load_config
from figmark.office import convert_office_to_pdf, find_soffice
from figmark.pipeline import convert

from .fakes import FakeClient

CORPUS = Path(__file__).resolve().parent.parent / "testfiler" / "office-eval"

pytestmark = pytest.mark.skipif(
    find_soffice() is None or not CORPUS.is_dir(),
    reason="needs LibreOffice + the local office-eval corpus",
)


@pytest.fixture(scope="module")
def run_office(tmp_path_factory, project_root):
    """Convert + pipeline a corpus file once per module; returns (result, client)."""
    import os

    os.environ.setdefault("FIGMARK_API_KEY", "sk-test-fake-key")
    cfg = load_config(project_root / "config.example.yaml")
    root = tmp_path_factory.mktemp("office-quality")
    cache: dict[str, tuple] = {}

    def _run(name: str):
        if name not in cache:
            src = CORPUS / name
            if not src.exists():
                pytest.skip(f"corpus file missing: {name}")
            work = root / src.stem
            pdf = convert_office_to_pdf(src, work, timeout=180)
            client = FakeClient("[FIGURBESKRIVNING]")
            result = convert(pdf, cfg, work / "out", client=client, quiet=True)
            cache[name] = (result, client)
        return cache[name]

    return _run


def test_docx_report_structure_and_tables(run_office):
    """skr-kommunbas: a 143-page Swedish account-plan report — title, section
    headings and the ruled tables must all survive."""
    result, client = run_office("skr-kommunbas.docx")
    md = result.markdown
    assert result.page_count == 143
    assert "# Kommun-Bas 25" in md
    assert "## Förord" in md
    assert md.count("| ---") >= 40, "the ruled account tables come through as Markdown"
    # The document embeds one image (the cover art) — exactly one description
    # call, however many pages the converter repeats it on.
    assert len(client.describe_prompts) == 1


def test_docx_consultation_phantom_images_stay_gone(run_office):
    """govuk consultation: 6 unique images. Before the drawn-instances fix this
    produced 222 phantom figures (every doc image listed on every page)."""
    result, client = run_office("govuk-social-care-consultation.docx")
    assert "# Future of social care inspection" in result.markdown
    assert len(client.describe_prompts) <= 8, (
        f"expected ≤8 unique image descriptions, got {len(client.describe_prompts)} "
        "— phantom resource-dict images are back or dedup broke"
    )


def test_pptx_ruled_table_cells_are_faithful(run_office):
    """cdc-vaccine-effectiveness: the VE summary table must keep column↔value
    attribution (spot-checked against the source deck)."""
    result, _ = run_office("cdc-vaccine-effectiveness.pptx")
    md = result.markdown
    assert "| Influenza Season |" in md
    assert "| 2010-11 | Treanor 2011 | WI, MI, NY, TN | 4,757 | 60 | 53, 66 |" in md


def test_xlsx_ruled_tables_extracted(run_office):
    """scb-amneslarare: ruled statistics tables become Markdown tables with the
    verified totals row intact."""
    result, _ = run_office("scb-amneslarare.xlsx")
    md = result.markdown
    assert md.count("| ---") >= 10
    assert "| Totalt antal examinerade |" in md
    assert "| 611 | 363 | 974 |" in md.replace("|  |", "|").replace("  ", " ") or "611" in md


def test_docx_footnote_text_survives(run_office):
    """poi-footnotes: the footnote body must not be dropped (T-044 phase 2 will
    format it; today it must at least be present as text)."""
    result, _ = run_office("poi-footnotes.docx")
    assert "snoska" in result.markdown


def test_docx_pictures_counted_once_each(run_office):
    """poi-pictures: 2 raster images + 3 vector-rendered pictures (wmf/emf/pict
    become drawings). With one-box banding (T-080) the 3 vector pictures sit in
    one visual band — no body paragraph between them — so they render as ONE
    region the model describes together: 3 figures, 3 description calls, none
    dropped, none double-counted. (Originally asserted 2: a pipeline regression
    had silently stopped scheduling diagram-description jobs; fixed with T-061.
    Asserted 5 before T-080 merged the vector band.)"""
    result, client = run_office("poi-pictures.docx")
    assert result.figure_count == 3
    assert len(client.describe_prompts) == 3
