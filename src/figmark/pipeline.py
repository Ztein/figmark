"""The conversion pipeline — one code path shared by the CLI and the API.

``convert`` runs the whole flow (classify → extract/OCR → find figures → detect
language → summarise → describe in parallel → assemble) and returns a
``ConversionResult`` with the Markdown and the artifact paths. ``main.run`` and the
API server both call it; the API injects its own client and runs it quietly.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from openai import APIError

from .annotate import AnnotationItem, annotate_pdf
from .boilerplate import strip_boilerplate
from .config import Config
from .context import ContextText, get_text_context_around
from .describe import cache_fingerprint, describe_image, is_skip, make_client
from .diagrams import (
    DiagramRegion,
    describe_diagram,
    find_diagram_regions,
    render_and_save_region,
    text_block_in_region,
)
from .images import MIN_IMAGE_HEIGHT, MIN_IMAGE_WIDTH, extract_images_from_page
from .ocr import (
    MIN_CHARS_PER_PAGE,
    MIN_MEAN_CONFIDENCE,
    ocr_page,
    ocr_page_with_vision,
    should_fallback,
)
from .output import PageData, assemble, build_figure_manifest, to_markdown
from .parallel import Job, run_jobs
from .pdf_loader import (
    GARBLE_WARN_RATIO,
    SCANNED_MIN_AVG_CHARS_PER_PAGE,
    DiagramBlock,
    ImageBlock,
    TextBlock,
    is_scanned,
    iter_page_blocks,
    iter_pages,
    open_pdf,
    page_needs_ocr,
    sort_blocks_reading_order,
    text_garble_ratio,
)
from .summarize import detect_language, summarize_document
from .tables import find_table_blocks, text_block_consumed
from .tagged import lang_code, tag_pdf
from .usage import TrackingClient, Usage, UsageTracker, estimate_cost


@dataclass(frozen=True)
class ConversionResult:
    """The outcome of a conversion: the Markdown plus where everything landed."""

    markdown: str
    markdown_path: Path
    raw_text_path: Path
    figures_manifest_path: Path
    output_dir: Path
    images_dir: Path
    annotated_pdf_path: Path | None
    tagged_pdf_path: Path | None
    page_count: int
    figure_count: int
    skipped_count: int
    language: str
    usage: Usage
    estimated_cost: float | None
    currency: str | None
    # (width, height) per page in PDF points, page order — consumed by the OCR
    # surface's pages[].dimensions (T-058).
    page_sizes: tuple[tuple[float, float], ...] = ()


logger = logging.getLogger("figmark.pipeline")


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
                if desc and not is_skip(desc):  # a [SKIP] (logo) diagram is not annotated (T-023)
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
            client,
            img.path,
            desc_path,
            cfg,
            context=context,
            doc_summary=doc_summary,
            language=language,
        )

    def store(text: str) -> None:
        page_data.descriptions[img.xref] = text

    return Job(label=label, func=run_describe, on_done=store)


def _make_diagram_job(
    label, client, region, desc_path, cfg, page_data, context, doc_summary, language
) -> Job:
    def run_describe() -> str:
        return describe_diagram(
            client,
            region,
            desc_path,
            cfg,
            context=context,
            doc_summary=doc_summary,
            language=language,
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
    tagged: bool = False,
    client=None,
    console=None,
    quiet: bool = False,
    shared_cache=None,
) -> ConversionResult:
    """Run the full conversion and return the Markdown + artifact paths.

    ``client`` defaults to a fresh OpenAI client from ``cfg``; the API injects its
    own (or a fake in tests). ``quiet`` suppresses progress output for non-TTY use.
    ``shared_cache`` (a ``SharedDescriptionCache``, T-061) lets figure/diagram
    descriptions be reused across requests and documents; ``None`` (the CLI)
    keeps the per-document disk cache only.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if client is None:
        client = make_client(cfg)

    # Wrap the client so every chat.completions.create records its token usage
    # (thread-safe — descriptions run in parallel). Cache hits make no call, so
    # they correctly contribute nothing.
    tracker = UsageTracker()
    client = TrackingClient(client, tracker)

    emit = _noop if quiet else log

    def emit_loud(msg: str) -> None:
        # Loud warnings (OCR rescue, Tesseract fallback, broken text layer) must
        # not vanish in container/server mode. Under quiet=True (no TTY) they go to
        # the structured logger so they survive into the API's JSON logs; on an
        # interactive run they show as the console banner instead. (T-032)
        if quiet:
            logger.warning(msg)
        else:
            loud(msg)

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
    # Document-level density is now only a logged hint — the actual OCR/text choice
    # is made per page (T-027), so a scanned page inside a text PDF (or vice versa)
    # is handled instead of silently lost.
    doc_hint_scanned = is_scanned(doc)
    hint = "scanned" if doc_hint_scanned else "text-encoded"
    emit(
        f"Text density: {avg_chars:.0f} chars/page on average "
        f"(threshold: {SCANNED_MIN_AVG_CHARS_PER_PAGE}; hint: {hint}) — deciding per page"
    )

    pages: list[PageData] = []
    page_regions: dict[int, list[DiagramRegion]] = {}

    for page_num, page in iter_pages(doc):
        emit(f"\nPage {page_num}/{len(doc)}")
        needs_ocr, reason = page_needs_ocr(page)
        page_data = PageData(
            page_num=page_num,
            is_ocr=needs_ocr,
            page_height=page.rect.height,
            page_width=page.rect.width,
        )

        # Shout when a page is OCR'd inside an otherwise text-encoded document —
        # that is exactly the content that used to be dropped silently.
        if needs_ocr and not doc_hint_scanned:
            emit_loud(f"PAGE {page_num}: OCR rescue in a text-encoded document — {reason}")
        else:
            emit(f"  → {'OCR' if needs_ocr else 'text'}: {reason}")

        if needs_ocr:
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
            # Warn (don't silently emit garbage) when the text layer looks broken —
            # e.g. a missing/bad font encoding producing mojibake (T-028).
            garble = text_garble_ratio(page.get_text("text"))
            if garble >= GARBLE_WARN_RATIO:
                emit_loud(
                    f"PAGE {page_num}: text layer looks broken ({garble:.0%} garbled "
                    "characters — likely a missing/bad font encoding). The extracted "
                    "text may be unusable; re-export or pre-OCR this PDF."
                )

        extraction = extract_images_from_page(
            doc, page, page_num, images_dir, skip_full_page=needs_ocr
        )
        page_data.images = extraction.images
        # Explain filtering so "0 saved" doesn't read like a bug (T-002).
        skip_notes = []
        if extraction.skipped_small:
            skip_notes.append(f"{extraction.skipped_small} < {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}")
        if extraction.skipped_full_page:
            skip_notes.append(f"{extraction.skipped_full_page} full-page")
        if extraction.skipped_not_drawn:
            skip_notes.append(f"{extraction.skipped_not_drawn} referenced-but-not-drawn")
        note = f" ({', '.join(skip_notes)} filtered)" if skip_notes else ""
        emit(f"  → {len(page_data.images)} image(s) saved{note}")

        # Diagram extraction: only for text-extracted pages (on OCR'd pages the
        # "diagrams" are already part of the page and captured by the OCR path).
        if cfg.diagrams.enabled and not needs_ocr:
            regions = find_diagram_regions(page, page_num)
            if regions:
                for region in regions:
                    render_and_save_region(page, region, diagrams_dir)
                    page_data.blocks.append(
                        DiagramBlock(bbox=region.bbox, region_index=region.index)
                    )
                page_regions[page_num] = regions
                emit(f"  → {len(regions)} diagram region(s) identified")
                # Drop the diagram's internal label text (axis labels, legends) so it
                # doesn't leak into the body — it's redundant with the rendered image
                # and its description. Conservative containment so body text merely
                # abutting the chart is kept, not deleted. (T-008)
                before = len(page_data.blocks)
                page_data.blocks = [
                    b
                    for b in page_data.blocks
                    if not (isinstance(b, TextBlock) and text_block_in_region(b.bbox, regions))
                ]
                dropped = before - len(page_data.blocks)
                if dropped:
                    emit(f"  → {dropped} in-diagram text block(s) suppressed")
                # Re-sort blocks so diagrams land in reading order with text/images
                # (column-aware, matching iter_page_blocks). (T-036)
                sort_blocks_reading_order(page_data.blocks, page.rect.width)

        # Table extraction (T-031): detect ruled data tables and emit them as
        # Markdown. Only on text pages; no API calls. The text spans a kept table
        # consumes are dropped so the cells are not also emitted as loose text.
        if cfg.tables.enabled and not needs_ocr:
            table_blocks = find_table_blocks(page, page_num)
            if table_blocks:
                page_data.blocks = [
                    b
                    for b in page_data.blocks
                    if not (isinstance(b, TextBlock) and text_block_consumed(b.bbox, table_blocks))
                ]
                page_data.blocks.extend(table_blocks)
                sort_blocks_reading_order(page_data.blocks, page.rect.width)
                emit(f"  → {len(table_blocks)} table(s) extracted")

        pages.append(page_data)

    total_diagrams = sum(len(regions) for regions in page_regions.values())
    if total_diagrams:
        diagram_descriptions_dir.mkdir(parents=True, exist_ok=True)

    # Fast text path (T-051): the document summary and the auto language detection
    # exist only to contextualise figure descriptions (language is also needed for
    # the tagged PDF's /Lang). With nothing to describe, both calls are pure
    # overhead — skip them, and say so (T-024: no silent behaviour change).
    total_images = sum(len(p.images) for p in pages)
    has_figures = bool(total_images or total_diagrams)
    if not has_figures:
        skip_msg = (
            "No figures or diagrams detected — skipping the document-summary"
            + ("" if tagged else " and language-detection")
            + " API call(s): they only contextualise figure descriptions (T-051)"
        )
        if quiet:
            logger.info(skip_msg)
        else:
            log(skip_msg)

    # Resolve the output language. "auto" detects the document's own language once,
    # then every description is told that language explicitly. Skipped when there
    # are no figures to describe and no tagged PDF (which needs the document /Lang).
    resolved_language = cfg.language.output
    if resolved_language.strip().lower() in ("auto", "document", "") and (has_figures or tagged):
        # A real API failure here (bad key, unreachable endpoint, exhausted
        # retries) would break every description call too — abort loudly instead
        # of masking it as a benign "using prompt default" (T-024 F2).
        try:
            detected = detect_language(client, pages, cfg, out_dir / "document_language.txt")
        except APIError as e:
            emit_loud(
                f"Language detection call failed ({type(e).__name__}: {e}). Aborting — "
                "the API key/endpoint looks misconfigured, which would fail every call."
            )
            raise
        if detected:
            resolved_language = detected
            emit(f"\nDocument language: {resolved_language}")

    # Document-type summary: best-effort context for every figure description.
    # Its only consumer is the figure prompts, so it is skipped outright when the
    # document has no figures (logged above, T-051).
    doc_summary = ""
    if cfg.document_summary.enabled and has_figures:
        try:
            doc_summary = summarize_document(
                client, pages, cfg, out_dir / "document_summary.txt", resolved_language
            )
        except APIError as e:
            emit_loud(
                f"Document summary call failed ({type(e).__name__}: {e}). Aborting — "
                "the API key/endpoint looks misconfigured, which would fail every call."
            )
            raise
        if doc_summary:
            emit(f"Document summary: {doc_summary}")

    # Gather ALL description jobs (images + diagrams). Cache hits resolve here so we
    # don't schedule needless workers; only real API calls reach run_jobs.
    jobs: list[Job] = []
    cache_hits = 0
    total_pending = sum(len(p.images) for p in pages) + total_diagrams

    # Config fingerprint folded into the cache filename: a change to the model,
    # prompt, resolved language, significance gate, context window, or document
    # summary now misses the cache and regenerates, instead of silently reusing a
    # description produced under the old config. (T-034)
    _ctx_fp = (cfg.context.enabled, cfg.context.words_before, cfg.context.words_after)
    _summary_fp = (cfg.document_summary.enabled, cfg.document_summary.prompt)
    image_fp = cache_fingerprint(
        cfg.api.model,
        cfg.description.prompt,
        resolved_language,
        cfg.significance.enabled,
        _ctx_fp,
        _summary_fp,
    )
    diagram_fp = cache_fingerprint(
        cfg.api.model,
        cfg.diagrams.prompt,
        resolved_language,
        cfg.significance.enabled,
        _ctx_fp,
        _summary_fp,
    )

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

    # The description cache is keyed by image CONTENT (digest), not page position:
    # the same embedded image (repeated logos/headers; LibreOffice-converted
    # documents repeat images across pages) is described once and reused. Within
    # a run, duplicate instances chain onto the first job instead of scheduling
    # their own API call (T-054). With a shared cross-request cache (T-061) the
    # same content is also reused across requests and other documents.
    pending_image_jobs: dict[str, Job] = {}
    duplicate_instances = 0
    shared_hits = 0

    def _with_shared_put(job: Job, shared_key: str) -> Job:
        def _put(text, _prev=job.on_done, _key=shared_key):
            _prev(text)
            shared_cache.put(_key, text)

        job.on_done = _put
        return job

    for page_data in pages:
        for img in page_data.images:
            cache_key = f"img-{img.digest or img.path.stem}-{image_fp}"
            desc_path = descriptions_dir / f"{cache_key}.txt"
            cached = desc_path.exists() and desc_path.read_text(encoding="utf-8").strip()
            if cached:
                page_data.descriptions[img.xref] = cached
                cache_hits += 1
                continue
            if shared_cache is not None:
                text = shared_cache.get(cache_key)
                if text:
                    page_data.descriptions[img.xref] = text
                    shared_hits += 1
                    continue
            pending = pending_image_jobs.get(cache_key)
            if pending is not None:
                duplicate_instances += 1

                def _chain(text, _prev=pending.on_done, _page=page_data, _xref=img.xref):
                    _prev(text)
                    _page.descriptions[_xref] = text

                pending.on_done = _chain
                continue
            label = f"page {page_data.page_num:>3} image   {img.index:>2}"
            ctx = _maybe_context(img.bbox)
            job = _make_image_job(
                label,
                client,
                img,
                desc_path,
                cfg,
                page_data,
                ctx,
                doc_summary,
                resolved_language,
            )
            if shared_cache is not None:
                job = _with_shared_put(job, cache_key)
            pending_image_jobs[cache_key] = job
            jobs.append(job)

        for region in page_regions.get(page_data.page_num, []):
            assert region.path is not None  # set by render_and_save_region above
            desc_path = diagram_descriptions_dir / f"{region.path.stem}-{diagram_fp}.txt"
            cached = desc_path.exists() and desc_path.read_text(encoding="utf-8").strip()
            if cached:
                page_data.diagram_descriptions[region.index] = cached
                cache_hits += 1
                continue
            # Diagrams share by the digest of their RENDERED pixels — position-
            # independent, so the same chart in another document reuses it.
            shared_key = None
            if shared_cache is not None:
                try:
                    render_digest = hashlib.sha256(region.path.read_bytes()).hexdigest()[:32]
                    shared_key = f"diag-{render_digest}-{diagram_fp}"
                except OSError:
                    shared_key = None
                if shared_key:
                    text = shared_cache.get(shared_key)
                    if text:
                        page_data.diagram_descriptions[region.index] = text
                        shared_hits += 1
                        continue
            label = f"page {page_data.page_num:>3} diagram {region.index:>2}"
            job = _make_diagram_job(
                label,
                client,
                region,
                desc_path,
                cfg,
                page_data,
                _maybe_context(region.bbox),
                doc_summary,
                resolved_language,
            )
            if shared_cache is not None and shared_key:
                job = _with_shared_put(job, shared_key)
            jobs.append(job)

    if duplicate_instances:
        emit(
            f"\n{duplicate_instances} repeated embedded image instance(s) share "
            "one description call each"
        )
    if shared_hits:
        shared_msg = (
            f"{shared_hits} description(s) reused from the shared cross-request cache (T-061)"
        )
        if quiet:
            logger.info(shared_msg)
        else:
            log(shared_msg)

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

    # Drop running headers/footers and page numbers before assembly (T-043).
    n_boilerplate = strip_boilerplate(pages)
    if n_boilerplate:
        emit(f"\nRemoved {n_boilerplate} running header/footer/page-number block(s)")

    emit("\nAssembling output …")
    raw_text, _full_text = assemble(pages, cfg)
    markdown = to_markdown(pages)

    raw_path = out_dir / "raw_text.txt"
    md_path = out_dir / f"{pdf_path.stem}.md"
    raw_path.write_text(raw_text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")

    # Machine-readable index of the extracted figures, for downstream follow-up
    # questions about a specific figure (T-041).
    figures_manifest_path = out_dir / f"{pdf_path.stem}.figures.json"
    figures_manifest_path.write_text(
        json.dumps(build_figure_manifest(pages), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    annotated_pdf_path: Path | None = None
    tagged_pdf_path: Path | None = None
    # Same described images/diagrams feed both the annotation and the tagged PDF.
    items = _collect_annotation_items(pages) if (annotate or tagged) else []
    # Close the source doc before reopening it for annotation/tagging.
    doc.close()
    if annotate:
        annotated_pdf_path = out_dir / f"{pdf_path.stem}_alt_text.pdf"
        emit(f"\nEmbedding {len(items)} descriptions as alt text → {annotated_pdf_path}")
        annotate_pdf(pdf_path, annotated_pdf_path, items)
    if tagged:
        tagged_pdf_path = out_dir / f"{pdf_path.stem}_tagged.pdf"
        emit(f"\nWriting tagged PDF (structure tree, {len(items)} figures) → {tagged_pdf_path}")
        tag_pdf(pdf_path, tagged_pdf_path, items, lang=lang_code(resolved_language))

    figure_count, skipped_count = _count_figures(pages)
    usage = tracker.snapshot()
    cost = estimate_cost(usage, cfg.api)
    return ConversionResult(
        markdown=markdown,
        markdown_path=md_path,
        raw_text_path=raw_path,
        figures_manifest_path=figures_manifest_path,
        output_dir=out_dir,
        images_dir=images_dir,
        annotated_pdf_path=annotated_pdf_path,
        tagged_pdf_path=tagged_pdf_path,
        page_count=len(pages),
        figure_count=figure_count,
        skipped_count=skipped_count,
        language=resolved_language,
        page_sizes=tuple((p.page_width, p.page_height) for p in pages),
        usage=usage,
        estimated_cost=(cost.amount if cost else None),
        currency=(cost.currency if cost else None),
    )
