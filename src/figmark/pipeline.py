"""The conversion pipeline — one code path shared by the CLI and the API.

``convert`` runs the whole flow (classify → extract/OCR → find figures → detect
language → summarise → describe in parallel → assemble) and returns a
``ConversionResult`` with the Markdown and the artifact paths. ``main.run`` and the
API server both call it; the API injects its own client and runs it quietly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .annotate import AnnotationItem, annotate_pdf
from .config import Config
from .context import ContextText, get_text_context_around
from .describe import describe_image, is_skip, make_client
from .diagrams import (
    DiagramRegion,
    describe_diagram,
    find_diagram_regions,
    render_and_save_region,
)
from .images import extract_images_from_page
from .ocr import (
    MIN_CHARS_PER_PAGE,
    MIN_MEAN_CONFIDENCE,
    ocr_page,
    ocr_page_with_vision,
    should_fallback,
)
from .output import PageData, assemble, to_markdown
from .parallel import Job, run_jobs
from .pdf_loader import (
    SCANNED_MIN_AVG_CHARS_PER_PAGE,
    DiagramBlock,
    ImageBlock,
    is_scanned,
    iter_page_blocks,
    iter_pages,
    open_pdf,
)
from .summarize import detect_language, summarize_document


@dataclass(frozen=True)
class ConversionResult:
    """The outcome of a conversion: the Markdown plus where everything landed."""

    markdown: str
    markdown_path: Path
    raw_text_path: Path
    output_dir: Path
    images_dir: Path
    annotated_pdf_path: Path | None
    page_count: int
    figure_count: int
    skipped_count: int
    language: str


def log(msg: str) -> None:
    print(msg, flush=True)


def loud(msg: str) -> None:
    """Shout out important decisions/fallbacks so they don't hide in the logs."""
    bar = "!" * 78
    print(f"\n{bar}\n!!! {msg}\n{bar}\n", flush=True)


def _noop(*_args, **_kwargs) -> None:
    pass


def _collect_annotation_items(pages: list[PageData]) -> list[AnnotationItem]:
    """Build the AnnotationItem list from described images + diagrams in page_data."""
    items: list[AnnotationItem] = []
    for page_data in pages:
        for img in page_data.images:
            if img.bbox is None:
                continue
            desc = page_data.descriptions.get(img.xref)
            if desc and not is_skip(desc):
                items.append(
                    AnnotationItem(
                        page_num=page_data.page_num,
                        bbox=img.bbox,
                        text=desc,
                        kind="Image",
                    )
                )
        for block in page_data.blocks:
            if isinstance(block, DiagramBlock):
                desc = page_data.diagram_descriptions.get(block.region_index)
                if desc:
                    items.append(
                        AnnotationItem(
                            page_num=page_data.page_num,
                            bbox=block.bbox,
                            text=desc,
                            kind="Diagram",
                        )
                    )
    return items


def _make_image_job(
    label, client, img, desc_path, cfg, page_data, context, doc_summary, language
) -> Job:
    """Capture the loop variables in a factory — otherwise the closure-in-loop trap."""

    def run_describe() -> str:
        return describe_image(
            client, img.path, desc_path, cfg,
            context=context, doc_summary=doc_summary, language=language,
        )

    def store(text: str) -> None:
        page_data.descriptions[img.xref] = text

    return Job(label=label, func=run_describe, on_done=store)


def _make_diagram_job(
    label, client, region, desc_path, cfg, page_data, context, doc_summary, language
) -> Job:
    def run_describe() -> str:
        return describe_diagram(
            client, region, desc_path, cfg,
            context=context, doc_summary=doc_summary, language=language,
        )

    def store(text: str) -> None:
        page_data.diagram_descriptions[region.index] = text

    return Job(label=label, func=run_describe, on_done=store)


def _count_figures(pages: list[PageData]) -> tuple[int, int]:
    """Return (described, skipped) figure counts across all pages."""
    described = 0
    skipped = 0
    for page in pages:
        for desc in page.descriptions.values():
            if is_skip(desc):
                skipped += 1
            elif desc.strip():
                described += 1
        for desc in page.diagram_descriptions.values():
            if desc.strip() and not is_skip(desc):
                described += 1
    return described, skipped


def convert(
    pdf_path: Path,
    cfg: Config,
    output_root: Path,
    *,
    annotate: bool = False,
    client=None,
    console=None,
    quiet: bool = False,
) -> ConversionResult:
    """Run the full conversion and return the Markdown + artifact paths.

    ``client`` defaults to a fresh OpenAI client from ``cfg``; the API injects its
    own (or a fake in tests). ``quiet`` suppresses progress output for non-TTY use.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if client is None:
        client = make_client(cfg)

    emit = _noop if quiet else log
    emit_loud = _noop if quiet else loud

    out_dir = output_root / pdf_path.stem
    images_dir = out_dir / "images"
    descriptions_dir = out_dir / "descriptions"
    diagrams_dir = out_dir / "diagrams"
    diagram_descriptions_dir = out_dir / "diagram_descriptions"
    out_dir.mkdir(parents=True, exist_ok=True)
    descriptions_dir.mkdir(parents=True, exist_ok=True)

    emit(f"Opening PDF: {pdf_path}")
    doc = open_pdf(pdf_path)
    emit(f"Page count: {len(doc)}")
    emit(f"Model: {cfg.api.model}  (base: {cfg.api.base_url})")

    avg_chars = sum(len(p.get_text("text").strip()) for p in doc) / max(1, len(doc))
    scanned = is_scanned(doc)
    emit(
        f"Text density: {avg_chars:.0f} chars/page on average "
        f"(threshold: {SCANNED_MIN_AVG_CHARS_PER_PAGE})"
    )
    if scanned:
        emit_loud(
            "PDF CLASSIFIED AS SCANNED — running OCR mode (Tesseract first, "
            "vision-OCR fallback on insufficient quality)"
        )
    else:
        emit("PDF classified as text-encoded — using direct text extraction.")

    pages: list[PageData] = []
    page_regions: dict[int, list[DiagramRegion]] = {}

    for page_num, page in iter_pages(doc):
        emit(f"\nPage {page_num}/{len(doc)}")
        page_data = PageData(page_num=page_num, is_ocr=scanned)

        if scanned:
            emit("  → Running Tesseract …")
            result = ocr_page(page, cfg)
            emit(
                f"    Tesseract: {len(result.text.strip())} chars, "
                f"confidence {result.mean_confidence:.1f}"
            )
            if should_fallback(result):
                reasons = []
                if len(result.text.strip()) < MIN_CHARS_PER_PAGE:
                    reasons.append(
                        f"chars {len(result.text.strip())} < threshold {MIN_CHARS_PER_PAGE}"
                    )
                if result.mean_confidence < MIN_MEAN_CONFIDENCE:
                    reasons.append(
                        f"confidence {result.mean_confidence:.1f} < threshold {MIN_MEAN_CONFIDENCE}"
                    )
                emit_loud(
                    f"FALLBACK ON PAGE {page_num}: Tesseract insufficient "
                    f"({'; '.join(reasons)}) — calling the vision model for OCR"
                )
                page_data.ocr_text = ocr_page_with_vision(page, client, cfg)
                emit(f"    Vision-OCR: {len(page_data.ocr_text.strip())} chars")
            else:
                page_data.ocr_text = result.text
        else:
            page_data.blocks = iter_page_blocks(page)
            n_text = sum(1 for b in page_data.blocks if not isinstance(b, ImageBlock))
            n_img = sum(1 for b in page_data.blocks if isinstance(b, ImageBlock))
            emit(f"  → {n_text} text block(s), {n_img} image block(s) (references)")

        page_data.images = extract_images_from_page(
            doc, page, page_num, images_dir, skip_full_page=scanned
        )
        emit(f"  → {len(page_data.images)} image(s) saved")

        # Diagram extraction: only for text-encoded PDFs (for scanned ones the
        # "diagrams" are already part of the page and captured by the OCR path).
        if cfg.diagrams.enabled and not scanned:
            regions = find_diagram_regions(page, page_num)
            if regions:
                for region in regions:
                    render_and_save_region(page, region, diagrams_dir)
                    page_data.blocks.append(
                        DiagramBlock(bbox=region.bbox, region_index=region.index)
                    )
                page_regions[page_num] = regions
                emit(f"  → {len(regions)} diagram region(s) identified")
                # Re-sort blocks so diagrams land in reading order with text/images.
                page_data.blocks.sort(key=lambda b: (round(b.bbox[1] / 10), b.bbox[0]))

        pages.append(page_data)

    total_diagrams = sum(len(regions) for regions in page_regions.values())
    if total_diagrams:
        diagram_descriptions_dir.mkdir(parents=True, exist_ok=True)

    # Resolve the output language. "auto" detects the document's own language once,
    # then every description is told that language explicitly.
    resolved_language = cfg.language.output
    if resolved_language.strip().lower() in ("auto", "document", ""):
        detected = ""
        try:
            detected = detect_language(client, pages, cfg, out_dir / "document_language.txt")
        except Exception as e:  # noqa: BLE001
            emit_loud(f"Language detection failed ({type(e).__name__}: {e}) — using prompt default")
        if detected:
            resolved_language = detected
            emit(f"\nDocument language: {resolved_language}")

    # Document-type summary: best-effort context for every figure description.
    doc_summary = ""
    if cfg.document_summary.enabled:
        try:
            doc_summary = summarize_document(
                client, pages, cfg, out_dir / "document_summary.txt", resolved_language
            )
        except Exception as e:  # noqa: BLE001
            emit_loud(f"Document summary failed ({type(e).__name__}: {e}) — continuing without it")
        if doc_summary:
            emit(f"Document summary: {doc_summary}")

    # Gather ALL description jobs (images + diagrams). Cache hits resolve here so we
    # don't schedule needless workers; only real API calls reach run_jobs.
    jobs: list[Job] = []
    cache_hits = 0
    total_pending = sum(len(p.images) for p in pages) + total_diagrams

    def _maybe_context(bbox) -> ContextText | None:
        if not cfg.context.enabled or bbox is None:
            return None
        return get_text_context_around(
            pages,
            page_num=page_data.page_num,
            bbox=bbox,
            words_before=cfg.context.words_before,
            words_after=cfg.context.words_after,
        )

    for page_data in pages:
        for img in page_data.images:
            desc_path = descriptions_dir / f"{img.path.stem}.txt"
            cached = desc_path.exists() and desc_path.read_text(encoding="utf-8").strip()
            if cached:
                page_data.descriptions[img.xref] = cached
                cache_hits += 1
                continue
            label = f"page {page_data.page_num:>3} image   {img.index:>2}"
            ctx = _maybe_context(img.bbox)
            jobs.append(
                _make_image_job(
                    label, client, img, desc_path, cfg, page_data, ctx, doc_summary,
                    resolved_language,
                )
            )

        for region in page_regions.get(page_data.page_num, []):
            desc_path = diagram_descriptions_dir / f"{region.path.stem}.txt"
            cached = desc_path.exists() and desc_path.read_text(encoding="utf-8").strip()
            if cached:
                page_data.diagram_descriptions[region.index] = cached
                cache_hits += 1
                continue
            label = f"page {page_data.page_num:>3} diagram {region.index:>2}"
            ctx = _maybe_context(region.bbox)
            jobs.append(
                _make_diagram_job(
                    label, client, region, desc_path, cfg, page_data, ctx, doc_summary,
                    resolved_language,
                )
            )

    if total_pending:
        if cache_hits:
            emit(f"\nDescriptions: {cache_hits} of {total_pending} loaded from cache")
        if jobs:
            header = (
                f"Describing {len(jobs)} via {cfg.api.model} "
                f"({cfg.concurrency.max_workers} in parallel)"
            )
            run_jobs(jobs, cfg.concurrency.max_workers, header, console=console, quiet=quiet)
        else:
            emit("\nEverything already cached — no API calls needed.")

    emit("\nAssembling output …")
    raw_text, _full_text = assemble(pages, cfg)
    markdown = to_markdown(pages)

    raw_path = out_dir / "raw_text.txt"
    md_path = out_dir / f"{pdf_path.stem}.md"
    raw_path.write_text(raw_text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")

    annotated_pdf_path: Path | None = None
    if annotate:
        items = _collect_annotation_items(pages)
        annotated_pdf_path = out_dir / f"{pdf_path.stem}_alt_text.pdf"
        emit(f"\nEmbedding {len(items)} descriptions as alt text → {annotated_pdf_path}")
        # Close the source doc first — we need to reopen the file cleanly.
        doc.close()
        annotate_pdf(pdf_path, annotated_pdf_path, items)
    else:
        doc.close()

    figure_count, skipped_count = _count_figures(pages)
    return ConversionResult(
        markdown=markdown,
        markdown_path=md_path,
        raw_text_path=raw_path,
        output_dir=out_dir,
        images_dir=images_dir,
        annotated_pdf_path=annotated_pdf_path,
        page_count=len(pages),
        figure_count=figure_count,
        skipped_count=skipped_count,
        language=resolved_language,
    )
